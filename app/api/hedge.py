"""The on-chain hedge of a weekend trade, in shadow (ADR-025, Version B).

The paper's design: when a customer trades at a weekend price, Yagnum
mirrors the trade on Jupiter so the guaranteed price is covered. What is
built here is that mirror, run end to end against the real chain - quote,
transaction, signature, mainnet simulation, fee arithmetic - and stopped one
step short of sending. Every weekend trade therefore gets two `hedge_legs`
rows that say what hedging it would have cost and, at settlement, what
Version B would have earned or lost on it. That is the evidence the
Version A / Version B decision needs.

WHICH WAY THE ENGINE TRADES

    customer sells 1 NVDA  ->  open: engine SELLS 1 NVDAx for USDC
                               close: engine BUYS 1 NVDAx back
    customer buys 1 NVDA   ->  open: engine BUYS 1 NVDAx with USDC
                               close: engine SELLS it

    A sell needs inventory: a DEX cannot short. Shadow mode records that as
    the simulation failing on an empty wallet, which is the honest answer.

NEVER BLOCKS MONEY. The engine calls `shadow_open` / `shadow_close` after
its journals; both swallow every failure into the row's `error` column and
return. A dead RPC endpoint can lose an observation, never a settlement.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

import jupiter
import solana
from config import settings
from models import HedgeLeg, WeekendTrade

SLIPPAGE_BPS = 50
_CENT = Decimal("0.01")
_MICRO = Decimal("0.000001")


def enabled() -> bool:
    return settings.hedge_mode == "shadow" and solana.engine_pubkey() is not None


def chain_side(customer_side: str, leg: str) -> str:
    """What the engine does with the token on this leg (see module doc)."""
    mirror = "sell" if customer_side == "sell" else "buy"
    if leg == "open":
        return mirror
    return "buy" if mirror == "sell" else "sell"


def _quote(mint: str, decimals: int, side: str, qty: Decimal, reference: Decimal) -> tuple[dict, Decimal, Decimal]:
    """Jupiter's quote for this leg. Returns (body, usd, tokens).

    sell: qty tokens -> USDC, exact on the token side.
    buy:  USDC -> tokens, sized from `reference` (the trade's own price), so
          the USDC side is exact and the token side is what it buys.
    """
    if side == "sell":
        body = jupiter.swap_quote(mint, jupiter.USDC_MINT, jupiter.to_base_units(qty, decimals))
        usd = jupiter.from_base_units(str(body["outAmount"]), jupiter.USDC_DECIMALS)
        return body, usd, qty
    notional = (qty * reference).quantize(_MICRO)
    body = jupiter.swap_quote(jupiter.USDC_MINT, mint, jupiter.to_base_units(notional, jupiter.USDC_DECIMALS))
    tokens = jupiter.from_base_units(str(body["outAmount"]), decimals)
    return body, notional, tokens


def _sol_usd() -> Decimal | None:
    try:
        quote = jupiter.prices([solana.SOL_MINT]).get(solana.SOL_MINT) or {}
        price = Decimal(str(quote.get("usdPrice") or "0"))
        return price if price > 0 else None
    except (jupiter.JupiterError, ArithmeticError):
        return None


def _open_leg(session: Session, trade: WeekendTrade) -> HedgeLeg | None:
    return session.execute(
        select(HedgeLeg).where(HedgeLeg.trade_id == trade.id, HedgeLeg.leg == "open").order_by(HedgeLeg.id.desc())
    ).scalars().first()


def _pnl(trade: WeekendTrade, opened: HedgeLeg, closing: HedgeLeg) -> None:
    """Fill the close leg's three P/L columns (module doc)."""
    if trade.p_close is None:
        return
    # Per token, times the trade's size. The close leg's swap cannot be sized
    # to the exact token count (a buy is quoted in USDC), so its `qty` can
    # differ slightly from the trade's; the price per token is what carries.
    if trade.side == "sell":
        broker = trade.qty * (trade.p_close - trade.p_open)
        chain = trade.qty * (opened.price - closing.price)
    else:
        broker = trade.qty * (trade.p_open - trade.p_close)
        chain = trade.qty * (closing.price - opened.price)
    gas = (opened.gas_usd or Decimal("0")) + (closing.gas_usd or Decimal("0"))
    closing.broker_pnl = broker.quantize(_CENT, rounding=ROUND_HALF_UP)
    closing.chain_pnl = chain.quantize(_CENT, rounding=ROUND_HALF_UP)
    closing.version_b_pnl = (broker + chain - gas).quantize(_CENT, rounding=ROUND_HALF_UP)


def shadow_leg(session: Session, trade: WeekendTrade, leg: str) -> HedgeLeg | None:
    """Build, sign, simulate and record one leg. Returns the row, or None
    when the hedge is disabled. Never raises: a failure is a row with
    `error` set and whatever was learned before it."""
    if not enabled():
        return None
    wallet = solana.engine_pubkey() or ""
    side = chain_side(trade.side, leg)
    token = jupiter.xstock_for(trade.symbol) or {}
    decimals = int(token.get("decimals") or 8)
    reference = trade.p_close if (leg == "close" and trade.p_close) else trade.p_open

    row = HedgeLeg(
        trade_id=trade.id,
        leg=leg,
        mode="shadow",
        side=side,
        token_symbol=trade.token_symbol,
        mint=trade.mint,
        wallet=wallet,
        qty=trade.qty,
        usd_amount=Decimal("0"),
        price=Decimal("0"),
        slippage_bps=SLIPPAGE_BPS,
        signed=False,
    )
    session.add(row)
    errors: list[str] = []

    # 1. The quote - the price this leg would get, for this exact size.
    try:
        body, usd, tokens = _quote(trade.mint, decimals, side, trade.qty, reference)
        row.qty = tokens
        row.usd_amount = usd
        row.price = usd / tokens if tokens else Decimal("0")
        impact = body.get("priceImpactPct")
        row.price_impact_pct = Decimal(str(impact)) if impact not in (None, "") else None
        row.route = ",".join(
            str(step.get("swapInfo", {}).get("label") or "?") for step in body.get("routePlan") or []
        )[:256]
    except (jupiter.JupiterError, ValueError, KeyError, ArithmeticError) as exc:
        errors.append(f"quote: {exc}")
        body = None

    # 2. The transaction Jupiter builds against the engine wallet.
    built = None
    if body is not None:
        try:
            built = jupiter.build_swap(body, wallet)
            row.compute_unit_limit = built.get("computeUnitLimit")
            row.priority_fee_lamports = built.get("prioritizationFeeLamports")
            row.last_valid_block_height = built.get("lastValidBlockHeight")
            sim_error = built.get("simulationError")
            if sim_error:
                row.jupiter_sim_error = str(sim_error.get("error") or sim_error)[:1000]
        except (jupiter.JupiterError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"build: {exc}")

    # 3. Sign locally when this host holds the key; simulate on mainnet.
    if built is not None:
        try:
            tx = solana.decode_transaction(str(built["swapTransaction"]))
            signatures = len(tx.signatures)
            row.base_fee_lamports = solana.BASE_FEE_LAMPORTS_PER_SIGNATURE * signatures
            keypair = solana.engine_keypair()
            if keypair is not None:
                tx = solana.sign(tx, keypair)
                row.signed = True
                row.signature = str(tx.signatures[0])
            simulated = solana.simulate(tx)
            row.rpc_units_consumed = simulated.get("units_consumed")
            if simulated.get("err") is not None:
                row.rpc_sim_error = str(simulated["err"])[:1000]
        except (solana.SolanaError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"simulate: {exc}")

    # 4. Rent: does the wallet already hold an account for this token?
    try:
        program = solana.account_owner(trade.mint) or solana.TOKEN_PROGRAM
        row.token_program = program
        ata = solana.associated_token_address(wallet, trade.mint, program)
        row.ata_exists = solana.account_owner(ata) is not None
        row.ata_rent_lamports = 0 if row.ata_exists else solana.rent_exempt_lamports()
    except (solana.SolanaError, ValueError) as exc:
        errors.append(f"rent: {exc}")

    # 5. Gas, in lamports and in dollars at this moment's SOL price.
    if row.base_fee_lamports is not None:
        row.gas_lamports = (
            row.base_fee_lamports + (row.priority_fee_lamports or 0) + (row.ata_rent_lamports or 0)
        )
        row.sol_usd = _sol_usd()
        if row.sol_usd is not None:
            row.gas_usd = (
                Decimal(row.gas_lamports) / Decimal(solana.LAMPORTS_PER_SOL) * row.sol_usd
            ).quantize(_MICRO, rounding=ROUND_HALF_UP)

    # 6. On the close leg, the Version B answer for this trade.
    if leg == "close":
        opened = _open_leg(session, trade)
        if opened is not None and opened.usd_amount > 0 and row.usd_amount > 0:
            _pnl(trade, opened, row)
        else:
            errors.append("pnl: no usable open leg")

    row.error = "; ".join(errors)[:2000] or None
    row.at = dt.datetime.now(dt.timezone.utc)
    session.commit()
    return row


def summary(row: HedgeLeg | None) -> str:
    """One line for the trade's event trail."""
    if row is None:
        return "hedge disabled"
    parts = [f"{row.side} {format(row.qty.normalize(), 'f')} {row.token_symbol} at {format(row.price.quantize(_CENT), 'f')}"]
    if row.gas_lamports is not None:
        gas = f"gas {row.gas_lamports} lamports"
        if row.gas_usd is not None:
            gas += f" (${format(row.gas_usd.quantize(Decimal('0.0001')), 'f')})"
        parts.append(gas)
    if row.rpc_sim_error:
        parts.append(f"simulation: {row.rpc_sim_error[:80]}")
    elif row.rpc_units_consumed:
        parts.append(f"simulated ok, {row.rpc_units_consumed} CU")
    if row.version_b_pnl is not None:
        parts.append(f"Version B P/L {format(row.version_b_pnl, 'f')}")
    if row.error:
        parts.append(f"errors: {row.error[:120]}")
    return " - ".join(parts)
