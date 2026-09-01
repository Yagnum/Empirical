"""The ERR engine: weekend trades, from Jupiter quote to Monday true-up.

This module is the paper's §6 running against real sandbox money (ADR-019).
The story of one SELL, which is the flow everything else mirrors:

  OPEN (a weekend, real or simulated)
    1. Jupiter's swap quote prices the sale - the bid, for the trader's
       exact size. That price is `p_open`.
    2. The reserve is computed from measured inputs (err.py, ADR-018) and
       journaled OUT of the trader's account into the firm account. Tagged
       "ERR escrow", so the escrow position is a query at the broker.
    3. The trader is advanced `qty * p_open` from the firm account, cash
       now. The advance is the product: immediacy while every market is
       closed. State: `provisional`.

  SETTLE (the next regulated session)
    4. The hedge: the shares are sold at the broker for real. The fill
       price is `p_close` - the first regulated price, which per ADR-017
       is what the trader must end at.
    5. The fill's proceeds are swept to the firm (they repay the advance),
       and the escrow comes back with the true-up:
           released = reserve + qty * (p_close - p_open)
       Price rose over the weekend -> the trader gets the rise on top of
       the full reserve. Price fell -> the fall comes out of the reserve.
       Net effect, always: the trader ended at `p_close`. Yagnum ends flat.
    6. If the gap ate MORE than the reserve, `released` is negative: the
       trade is `breached`, nothing comes back, and the excess is debited
       from the account - escrow is collateral, not a cap (ADR-017).

  A BUY is the mirror: the trader pays `qty * p_open` up front plus the
  reserve; settlement buys the shares for real, the firm reimburses the
  fill, and the escrow returns with the true-up reversed in sign.

  DEV-ONLY "injected" settlement skips step 4: `p_close` is chosen
  (p_open * (1 + gap)) instead of filled, and only the escrow half of the
  books runs. It exists to watch step 6 happen without waiting months for
  a real 4-sigma Monday. It never places an order and never runs outside
  development.

Every cash movement is a real Alpaca journal with a description tag, and
every step appends a `weekend_trade_events` row carrying the Alpaca id
that proves it. Money is Decimal; strings at the boundaries (ADR-010).
"""

from __future__ import annotations

import datetime as dt
import time
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import alpaca
import err
import jupiter
import sessions
from config import settings
from models import WeekendTrade, WeekendTradeEvent

_CENT = Decimal("0.01")

# How hard settle() tries to see the hedge fill before handing back
# "awaiting_settlement". A market order in the regular session fills in
# sandbox within a second or two; an extended-hours limit may take longer
# or never - the caller can simply settle again.
_FILL_POLL_TRIES = 6
_FILL_POLL_SECONDS = 1.5

# How far past the last trade an extended-hours limit is priced to make it
# marketable: sells 0.5% under, buys 0.5% over. Tight enough to be honest,
# loose enough to cross the spread.
_MARKETABLE_OFFSET = Decimal("0.005")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _require_firm_account() -> str:
    if not settings.alpaca_firm_account_id:
        raise HTTPException(status_code=503, detail="weekend_engine_unavailable: no firm account configured")
    return settings.alpaca_firm_account_id


def _event(
    session: Session,
    trade: WeekendTrade,
    kind: str,
    *,
    amount: Decimal | None = None,
    ref: str | None = None,
    detail: str | None = None,
) -> None:
    session.add(
        WeekendTradeEvent(
            trade_id=trade.id,
            kind=kind,
            amount=amount,
            alpaca_ref=ref,
            detail=detail,
        )
    )
    session.commit()


def _journal(
    session: Session,
    trade: WeekendTrade,
    *,
    from_account: str,
    to_account: str,
    amount: Decimal,
    kind: str,
    description: str,
) -> str | None:
    """One tagged cash movement, recorded as an event. Zero moves nothing."""
    amount = _money(amount)
    if amount <= 0:
        return None
    try:
        journal = alpaca.create_journal(
            from_account, to_account, amount, description=description
        )
    except alpaca.AlpacaError as exc:
        _event(session, trade, "error", detail=f"{kind} journal failed: {exc.message}")
        raise alpaca.http_error(exc) from exc
    journal_id = str(journal.get("id", "")) or None
    _event(session, trade, kind, amount=amount, ref=journal_id, detail=description)
    return journal_id


# ---------------------------------------------------------------------------
# Pricing (shared by the preview and the open)
# ---------------------------------------------------------------------------


def price_trade(symbol: str, side: str, qty: Decimal) -> dict:
    """Jupiter's executable price plus the reserve for this exact trade.

    Raises 404 `no_token` when no xStock mirrors the symbol and 502 when
    Jupiter cannot be reached - the same contract as /market/token.
    """
    underlying = symbol.upper()
    try:
        token = jupiter.xstock_for(underlying)
        if token is None:
            raise HTTPException(status_code=404, detail="no_token")
        quote = jupiter.executable_price(token, side, qty)
    except jupiter.JupiterError as exc:
        raise HTTPException(status_code=502, detail=f"jupiter_unreachable: {exc.message}") from exc

    p_open = quote["price"]
    sizing = err.compute(underlying, qty, p_open)
    return {"token": token, "quote": quote, "p_open": p_open, "sizing": sizing}


# ---------------------------------------------------------------------------
# Opening a weekend trade
# ---------------------------------------------------------------------------


OPEN_STATES = ("provisional", "awaiting_settlement")


def committed_shares(session: Session, account_id: str, symbol: str) -> Decimal:
    """Shares this account has weekend-sold but not yet settled (ADR-022).

    They are still in the brokerage account - the sandbox cannot journal
    securities - so the engine keeps this ledger lock instead: every path
    that could sell them again (the regular ticket, a second weekend sell,
    reset-balance) subtracts this figure first.
    """
    total = session.execute(
        select(func.coalesce(func.sum(WeekendTrade.qty), 0)).where(
            WeekendTrade.alpaca_account_id == account_id,
            WeekendTrade.symbol == symbol.upper(),
            WeekendTrade.side == "sell",
            WeekendTrade.state.in_(OPEN_STATES),
        )
    ).scalar_one()
    return Decimal(str(total))


def open_trade_count(session: Session, account_id: str) -> int:
    return session.execute(
        select(func.count()).select_from(WeekendTrade).where(
            WeekendTrade.alpaca_account_id == account_id,
            WeekendTrade.state.in_(OPEN_STATES),
        )
    ).scalar_one()


def sellable_shares(account_id: str, symbol: str, committed: Decimal) -> Decimal:
    """What the account can still sell: the broker's available figure minus
    the shares already committed to open weekend trades."""
    try:
        positions = alpaca.list_positions(account_id)
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc
    for position in positions:
        if str(position.get("symbol", "")).upper() == symbol:
            available = Decimal(str(position.get("qty_available") or position.get("qty") or "0"))
            return max(available - committed, Decimal("0"))
    return Decimal("0")


def _check_sell_shares(session: Session, account_id: str, symbol: str, qty: Decimal) -> None:
    committed = committed_shares(session, account_id, symbol)
    free = sellable_shares(account_id, symbol, committed)
    if free >= qty:
        return
    if committed > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"insufficient_shares: {format(committed, 'f')} of your {symbol} shares are already "
                f"committed to a weekend trade that settles when the market reopens. "
                f"You can sell {format(free, 'f')} more now."
            ),
        )
    raise HTTPException(
        status_code=400,
        detail=f"insufficient_shares: you hold {format(free, 'f')} {symbol} available to sell",
    )


def _check_buy_cash(account_id: str, needed: Decimal) -> None:
    try:
        account = alpaca.get_trading_account(account_id)
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc
    cash = Decimal(str(account.get("cash") or "0"))
    if cash < needed:
        raise HTTPException(
            status_code=400,
            detail=f"insufficient_cash: this needs {_fmt(_money(needed))}, the account holds {_fmt(_money(cash))}",
        )


def open_trade(
    session: Session,
    *,
    user_id: str,
    account_id: str,
    symbol: str,
    side: str,
    qty: Decimal,
) -> WeekendTrade:
    """Steps 1-3: price, reserve, escrow, advance. Ends `provisional`."""
    firm = _require_firm_account()
    priced = price_trade(symbol, side, qty)
    token = priced["token"]
    p_open = priced["p_open"]
    sizing = priced["sizing"]
    notional = _money(qty * p_open)

    if side == "sell":
        _check_sell_shares(session, account_id, symbol.upper(), qty)
    else:
        _check_buy_cash(account_id, notional + sizing["reserve"])

    trade = WeekendTrade(
        clerk_user_id=user_id,
        alpaca_account_id=account_id,
        symbol=symbol.upper(),
        token_symbol=token["symbol"],
        mint=token["mint"],
        side=side,
        qty=qty,
        p_open=p_open,
        sigma=sizing["sigma"],
        z=sizing["z"],
        reserve=sizing["reserve"],
        fees=sizing["fees"],
        state="provisional",
        simulated=sessions.weekend_override(),
    )
    session.add(trade)
    session.commit()
    _event(
        session,
        trade,
        "opened",
        amount=notional,
        detail=(
            f"{side} {_fmt(qty)} {trade.symbol} via {trade.token_symbol} at "
            f"{_fmt(p_open)} (Jupiter quote, impact {priced['quote']['price_impact_pct']}%)"
        ),
    )

    tag = f"weekend trade {trade.id}"
    trade.escrow_journal_id = _journal(
        session,
        trade,
        from_account=account_id,
        to_account=firm,
        amount=sizing["reserve"],
        kind="escrow_reserved",
        description=f"ERR escrow - {tag}",
    )

    if side == "sell":
        # The advance: sold now means paid now.
        trade.advance_journal_id = _journal(
            session,
            trade,
            from_account=firm,
            to_account=account_id,
            amount=notional,
            kind="advance_paid",
            description=f"ERR advance ({_fmt(qty)} {trade.symbol} @ {_fmt(_money(p_open))}) - {tag}",
        )
    else:
        # The mirror: bought now means paid-for now.
        trade.advance_journal_id = _journal(
            session,
            trade,
            from_account=account_id,
            to_account=firm,
            amount=notional,
            kind="charge_paid",
            description=f"ERR purchase charge ({_fmt(qty)} {trade.symbol} @ {_fmt(_money(p_open))}) - {tag}",
        )
    session.commit()
    return trade


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def _true_up(trade: WeekendTrade, p_close: Decimal) -> Decimal:
    """Signed from the trader's side (see module docstring step 5)."""
    gap_value = trade.qty * (p_close - trade.p_open)
    return gap_value if trade.side == "sell" else -gap_value


def _event_kinds(session: Session, trade: WeekendTrade) -> set[str]:
    rows = session.execute(
        select(WeekendTradeEvent.kind).where(WeekendTradeEvent.trade_id == trade.id)
    )
    return {kind for (kind,) in rows}


def _reconcile(session: Session, trade: WeekendTrade, *, sweep: bool) -> WeekendTrade:
    """Steps 5-6 against `trade.p_close`. Idempotent: a retry after a failed
    journal skips the steps whose events already exist."""
    firm = _require_firm_account()
    p_close = trade.p_close
    assert p_close is not None
    done = _event_kinds(session, trade)
    tag = f"weekend trade {trade.id}"
    fill_value = _money(trade.qty * p_close)

    if sweep and "hedge_swept" not in done:
        if trade.side == "sell":
            # The real sale's proceeds repay the advance.
            _journal(
                session,
                trade,
                from_account=trade.alpaca_account_id,
                to_account=firm,
                amount=fill_value,
                kind="hedge_swept",
                description=f"ERR hedge proceeds swept - {tag}",
            )
        else:
            # The real purchase came out of the trader's cash; the firm
            # reimburses it - the trader already paid at p_open.
            _journal(
                session,
                trade,
                from_account=firm,
                to_account=trade.alpaca_account_id,
                amount=fill_value,
                kind="hedge_swept",
                description=f"ERR hedge purchase reimbursed - {tag}",
            )

    true_up = trade.true_up if trade.true_up is not None else _true_up(trade, p_close)
    trade.true_up = true_up
    released = trade.reserve + true_up

    if released >= 0:
        if "escrow_released" not in done:
            _journal(
                session,
                trade,
                from_account=firm,
                to_account=trade.alpaca_account_id,
                amount=released,
                kind="escrow_released",
                description=f"ERR escrow released with true-up - {tag}",
            )
        trade.escrow_returned = _money(released)
        trade.shortfall = None
        trade.state = "settled"
    else:
        shortfall = -released
        if "shortfall_debited" not in done:
            _journal(
                session,
                trade,
                from_account=trade.alpaca_account_id,
                to_account=firm,
                amount=shortfall,
                kind="shortfall_debited",
                description=f"ERR shortfall beyond escrow - {tag}",
            )
        trade.escrow_returned = Decimal("0")
        trade.shortfall = _money(shortfall)
        trade.state = "breached"
        _event(
            session,
            trade,
            "breached",
            amount=_money(shortfall),
            detail="the weekend gap exceeded the whole reserve (ADR-017: collateral, not a cap)",
        )

    trade.settled_at = dt.datetime.now(dt.timezone.utc)
    session.commit()
    return trade


def _marketable_limit(symbol: str, side: str) -> Decimal:
    try:
        last = Decimal(str(alpaca.latest_trade(symbol).get("p") or "0"))
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc
    if last <= 0:
        raise HTTPException(status_code=502, detail="no_last_trade_to_price_the_hedge")
    offset = -_MARKETABLE_OFFSET if side == "sell" else _MARKETABLE_OFFSET
    return _money(last * (1 + offset))


def _place_hedge(session: Session, trade: WeekendTrade) -> None:
    """Step 4: the real order, shaped for whichever session is live NOW.

    The session is the *scheduled* one - the dev override fakes the app's
    clock, never the broker's. Regular hours get a market order; premarket
    and after-hours get a marketable limit with `extended_hours` (limit-only
    windows); overnight tries the 24/5 session the same way - whether the
    sandbox accepts that is exactly what the ADR-019 8:05 PM test asks.
    """
    live = sessions.scheduled_session()
    if live == sessions.WEEKEND:
        raise HTTPException(
            status_code=409,
            detail="market_closed: no regulated session is open to settle into (use injected mode in dev)",
        )

    payload: dict = {
        "symbol": trade.symbol,
        "qty": _fmt(trade.qty),
        "side": trade.side,
        "time_in_force": "day",
    }
    if live == sessions.REGULAR:
        payload["type"] = "market"
    else:
        payload["type"] = "limit"
        payload["limit_price"] = _fmt(_marketable_limit(trade.symbol, trade.side))
        payload["extended_hours"] = True

    try:
        order = alpaca.create_order(trade.alpaca_account_id, payload)
    except alpaca.AlpacaError as exc:
        _event(session, trade, "error", detail=f"hedge order refused ({live}): {exc.message}")
        raise HTTPException(status_code=400, detail=f"alpaca_rejected: {exc.message}") from exc

    trade.hedge_order_id = str(order.get("id", "")) or None
    trade.settlement_mode = "market"
    trade.state = "awaiting_settlement"
    session.commit()
    _event(
        session,
        trade,
        "hedge_placed",
        ref=trade.hedge_order_id,
        detail=f"{payload['type']} {trade.side} in the {live} session"
        + (f" at {payload.get('limit_price')}" if "limit_price" in payload else ""),
    )


def _check_hedge_fill(session: Session, trade: WeekendTrade, *, wait: bool) -> WeekendTrade:
    """Poll the hedge order; on a fill, record p_close and reconcile."""
    tries = _FILL_POLL_TRIES if wait else 1
    for attempt in range(tries):
        try:
            order = alpaca.get_order(trade.alpaca_account_id, trade.hedge_order_id or "")
        except alpaca.AlpacaError as exc:
            raise alpaca.http_error(exc) from exc
        status = str(order.get("status", ""))
        if status == "filled":
            trade.p_close = Decimal(str(order.get("filled_avg_price")))
            session.commit()
            _event(
                session,
                trade,
                "hedge_filled",
                amount=_money(trade.qty * trade.p_close),
                ref=trade.hedge_order_id,
                detail=f"filled at {order.get('filled_avg_price')}",
            )
            return _reconcile(session, trade, sweep=True)
        if status in ("canceled", "expired", "rejected"):
            # The hedge died without filling; the trade goes back to
            # provisional so a later settle can place a fresh one.
            _event(session, trade, "hedge_lost", ref=trade.hedge_order_id, detail=f"order {status}")
            trade.hedge_order_id = None
            trade.settlement_mode = None
            trade.state = "provisional"
            session.commit()
            return trade
        if attempt + 1 < tries:
            time.sleep(_FILL_POLL_SECONDS)
    # Still working (queued for the session, or waiting on its limit).
    return trade


def settle(
    session: Session,
    trade: WeekendTrade,
    *,
    mode: str,
    gap: Decimal | None = None,
) -> WeekendTrade:
    """Advance one trade toward settled, whatever state it is in.

    mode "market":   place the hedge if none is working, then wait briefly
                     for the fill and reconcile. Call again later if it
                     comes back still `awaiting_settlement`.
    mode "injected": dev only. p_close = p_open * (1 + gap); no order, no
                     advance repayment - only the escrow half of the books,
                     which is the half the gap maths lives in.
    """
    if trade.state in ("settled", "breached"):
        raise HTTPException(status_code=409, detail=f"already_{trade.state}")

    if mode == "injected":
        if not sessions.dev_override_allowed():
            raise HTTPException(status_code=404, detail="not_found")
        if trade.state != "provisional":
            raise HTTPException(
                status_code=409,
                detail="hedge_already_working: a real order is out; settle with mode=market",
            )
        if gap is None:
            raise HTTPException(status_code=422, detail="gap_required_for_injected_mode")
        trade.settlement_mode = "injected"
        trade.injected_gap = gap
        trade.p_close = trade.p_open * (Decimal("1") + gap)
        session.commit()
        _event(
            session,
            trade,
            "gap_injected",
            detail=f"p_close set to p_open x (1 + {format(gap, 'f')}) = {_fmt(_money(trade.p_close))} - no real order",
        )
        return _reconcile(session, trade, sweep=False)

    if mode != "market":
        raise HTTPException(status_code=422, detail="mode_must_be_market_or_injected")

    if trade.state == "provisional":
        _place_hedge(session, trade)
        return _check_hedge_fill(session, trade, wait=True)

    # awaiting_settlement: either the fill landed since last time, or the
    # reconciliation itself needs finishing (p_close known, journals not).
    if trade.p_close is not None:
        return _reconcile(session, trade, sweep=True)
    return _check_hedge_fill(session, trade, wait=True)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def list_open_trades(session: Session) -> list[WeekendTrade]:
    """Every trade, any account, that still needs the market: oldest first."""
    rows = session.execute(
        select(WeekendTrade)
        .where(WeekendTrade.state.in_(OPEN_STATES))
        .order_by(WeekendTrade.id)
    )
    return [trade for (trade,) in rows]


def settle_all_open(session: Session) -> dict:
    """The scheduled settlement (ADR-023): every open trade, mode=market.

    One trade's failure never stops the next: the broker refusing one hedge
    is recorded on that trade's event trail and counted, and the loop moves
    on. Returns a tally plus one log line per trade for the job's output.
    """
    summary: dict = {"settled": 0, "breached": 0, "awaiting": 0, "failed": 0, "log": []}
    if sessions.scheduled_session() == sessions.WEEKEND:
        summary["log"].append("no regulated session open; nothing settled")
        return summary
    for trade in list_open_trades(session):
        label = f"#{trade.id} {trade.side} {_fmt(trade.qty)} {trade.symbol}"
        try:
            trade = settle(session, trade, mode="market")
        except HTTPException as exc:
            summary["failed"] += 1
            summary["log"].append(f"{label}: failed - {exc.detail}")
            continue
        if trade.state in ("settled", "breached"):
            summary[trade.state] += 1
            summary["log"].append(
                f"{label}: {trade.state} at {_fmt(_money(trade.p_close))}, "
                f"reserve back {_fmt(trade.escrow_returned or Decimal('0'))}"
                + (f", shortfall {_fmt(trade.shortfall)}" if trade.shortfall else "")
            )
        else:
            summary["awaiting"] += 1
            summary["log"].append(f"{label}: hedge {trade.hedge_order_id} still working")
    return summary


def list_trades(session: Session, account_id: str, limit: int = 50) -> list[WeekendTrade]:
    rows = session.execute(
        select(WeekendTrade)
        .where(WeekendTrade.alpaca_account_id == account_id)
        .order_by(WeekendTrade.created_at.desc(), WeekendTrade.id.desc())
        .limit(limit)
    )
    return [trade for (trade,) in rows]


def get_trade(session: Session, account_id: str, trade_id: int) -> WeekendTrade:
    trade = session.get(WeekendTrade, trade_id)
    if trade is None or trade.alpaca_account_id != account_id:
        raise HTTPException(status_code=404, detail="trade_not_found")
    return trade


def trade_events(session: Session, trade: WeekendTrade) -> list[WeekendTradeEvent]:
    rows = session.execute(
        select(WeekendTradeEvent)
        .where(WeekendTradeEvent.trade_id == trade.id)
        .order_by(WeekendTradeEvent.at, WeekendTradeEvent.id)
    )
    return [event for (event,) in rows]
