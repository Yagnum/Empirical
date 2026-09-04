"""The shadow hedge (ADR-025): direction, fee arithmetic, and the Version B
P/L, with Jupiter and the chain replaced by fakes. Signing is exercised for
real with a throwaway keypair - it is local and free."""

from decimal import Decimal

import pytest
from solders.keypair import Keypair

import hedge
import solana
from config import settings
from models import HedgeLeg, WeekendTrade


@pytest.mark.parametrize(
    "customer, leg, expected",
    [
        ("sell", "open", "sell"),
        ("sell", "close", "buy"),
        ("buy", "open", "buy"),
        ("buy", "close", "sell"),
    ],
)
def test_engine_mirrors_the_customer_then_unwinds(customer, leg, expected):
    assert hedge.chain_side(customer, leg) == expected


def test_disabled_without_a_wallet():
    assert hedge.enabled() is False


def test_enabled_with_a_public_key_only(monkeypatch):
    monkeypatch.setattr(settings, "hedge_mode", "shadow")
    monkeypatch.setattr(settings, "solana_engine_pubkey", str(Keypair().pubkey()))
    assert hedge.enabled() is True
    assert solana.engine_keypair() is None


def test_keypair_round_trip(monkeypatch):
    import base58

    keypair = Keypair()
    monkeypatch.setattr(settings, "solana_engine_keypair", base58.b58encode(bytes(keypair)).decode())
    assert solana.engine_pubkey() == str(keypair.pubkey())


def test_associated_token_address_is_deterministic():
    owner = "G7Zr6w2CTfBkrBVr3Xj5PvEqt5R7ZJDdrh8GiEDYrzAZ"
    mint = "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh"
    first = solana.associated_token_address(owner, mint, solana.TOKEN_2022_PROGRAM)
    second = solana.associated_token_address(owner, mint, solana.TOKEN_2022_PROGRAM)
    assert first == second
    assert first != solana.associated_token_address(owner, mint, solana.TOKEN_PROGRAM)


def _trade(side="sell", p_open="230", p_close=None) -> WeekendTrade:
    trade = WeekendTrade(
        clerk_user_id="u",
        alpaca_account_id="a",
        symbol="NVDA",
        token_symbol="NVDAx",
        mint="Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh",
        side=side,
        qty=Decimal("2"),
        p_open=Decimal(p_open),
        sigma=Decimal("0.02"),
        z=Decimal("3.7"),
        reserve=Decimal("40"),
        fees=Decimal("0"),
    )
    trade.id = 7
    trade.p_close = Decimal(p_close) if p_close else None
    return trade


def _leg(price, gas_usd="0.19") -> HedgeLeg:
    return HedgeLeg(price=Decimal(price), usd_amount=Decimal(price) * 2, qty=Decimal("2"), gas_usd=Decimal(gas_usd))


def test_version_b_pnl_for_a_customer_sell():
    # Customer sold at 230. Monday the share fetched 233 (broker +6 on 2
    # shares); the token was sold at 230.80 and bought back at 233.50
    # (chain -5.40); two legs of gas.
    trade = _trade("sell", "230", "233")
    closing = _leg("233.50")
    hedge._pnl(trade, _leg("230.80"), closing)
    assert closing.broker_pnl == Decimal("6.00")
    assert closing.chain_pnl == Decimal("-5.40")
    assert closing.version_b_pnl == Decimal("0.22")  # 6.00 - 5.40 - 0.38


def test_version_b_pnl_for_a_customer_buy():
    # Customer bought at 230; Monday the share cost 228 (broker +4 on 2);
    # token bought at 230.90, sold at 228.20 (chain -5.40).
    trade = _trade("buy", "230", "228")
    closing = _leg("228.20")
    hedge._pnl(trade, _leg("230.90"), closing)
    assert closing.broker_pnl == Decimal("4.00")
    assert closing.chain_pnl == Decimal("-5.40")
    assert closing.version_b_pnl == Decimal("-1.78")


def test_shadow_leg_records_fees_and_simulation(monkeypatch):
    """Every network hop faked; the row must carry the fee arithmetic:
    base 5,000 x signatures + Jupiter's priority fee + rent when the wallet
    has no token account, converted at the SOL price."""
    import jupiter

    keypair = Keypair()
    monkeypatch.setattr(settings, "hedge_mode", "shadow")
    monkeypatch.setattr(settings, "solana_engine_pubkey", str(keypair.pubkey()))
    monkeypatch.setattr(jupiter, "xstock_for", lambda symbol: {"decimals": 8})
    monkeypatch.setattr(
        jupiter,
        "swap_quote",
        lambda i, o, amount: {"outAmount": "461600000", "priceImpactPct": "0.0002", "routePlan": [{"swapInfo": {"label": "Raydium CLMM"}}]},
    )
    built = {
        "swapTransaction": "fake",
        "computeUnitLimit": 1_400_000,
        "prioritizationFeeLamports": 12_345,
        "lastValidBlockHeight": 1,
        "simulationError": {"error": "Attempt to debit an account but found no record of a prior credit."},
    }
    monkeypatch.setattr(jupiter, "build_swap", lambda quote, wallet: built)
    monkeypatch.setattr(jupiter, "prices", lambda mints: {solana.SOL_MINT: {"usdPrice": "100"}})

    class Tx:
        signatures = [None]

    monkeypatch.setattr(solana, "decode_transaction", lambda b64: Tx())
    monkeypatch.setattr(solana, "simulate", lambda tx: {"err": "AccountNotFound", "units_consumed": 0, "logs": []})
    owners = {"Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh": solana.TOKEN_2022_PROGRAM}
    monkeypatch.setattr(solana, "account_owner", lambda address: owners.get(address))
    monkeypatch.setattr(solana, "rent_exempt_lamports", lambda size=165: 2_000_000)

    class Session:
        def __init__(self):
            self.rows = []

        def add(self, row):
            self.rows.append(row)

        def commit(self):
            pass

    session = Session()
    row = hedge.shadow_leg(session, _trade("sell"), "open")
    assert row is session.rows[0]
    assert row.side == "sell" and row.leg == "open" and row.mode == "shadow"
    assert row.usd_amount == Decimal("461.6") and row.price == Decimal("230.8")
    assert row.route == "Raydium CLMM"
    assert row.token_program == solana.TOKEN_2022_PROGRAM
    assert row.ata_exists is False and row.ata_rent_lamports == 2_000_000
    assert row.base_fee_lamports == 5_000 and row.priority_fee_lamports == 12_345
    assert row.gas_lamports == 2_017_345
    assert row.gas_usd == Decimal("0.201735")  # 2,017,345 / 1e9 x $100
    assert row.jupiter_sim_error.startswith("Attempt to debit")
    assert row.rpc_sim_error == "AccountNotFound"
    assert row.signed is False  # public key only on this host
    assert row.error is None
    assert "gas 2017345 lamports ($0.2017)" in hedge.summary(row)


def test_shadow_leg_survives_a_dead_chain(monkeypatch):
    import jupiter

    monkeypatch.setattr(settings, "hedge_mode", "shadow")
    monkeypatch.setattr(settings, "solana_engine_pubkey", str(Keypair().pubkey()))
    monkeypatch.setattr(jupiter, "xstock_for", lambda symbol: None)

    def boom(*args, **kwargs):
        raise jupiter.JupiterError("quote host down")

    monkeypatch.setattr(jupiter, "swap_quote", boom)
    monkeypatch.setattr(solana, "account_owner", lambda address: (_ for _ in ()).throw(solana.SolanaError("rpc down")))

    class Session:
        def add(self, row):
            self.row = row

        def commit(self):
            pass

    session = Session()
    row = hedge.shadow_leg(session, _trade("buy"), "open")
    assert row.error == "quote: quote host down; rent: rpc down"
    assert row.gas_lamports is None
