"""Simulated traders driven by a language model (ADR-026).

Eight personas, each with its own sandbox brokerage account. Every tick
(the cron runs hourly; two groups alternate) each persona reads a briefing - the
hour, its cash and positions, its open weekend trades, and the recent
prices and spreads of the symbols it watches - and answers with one JSON
intent: buy, sell, or hold. The intent goes through the same doors a
person's would:

    weekend            weekend.open_trade  (the ERR engine, source="sim")
    regular hours      a market day order at the broker
    premarket / after  a marketable limit day order, extended_hours=True
    overnight          nothing - that window queues at the broker (ADR-024)

THE MODEL NEVER TOUCHES MONEY. It sees numbers and returns a wish; the
engine's own checks (shares committed, cash, size caps) accept or refuse
it exactly as they would for a person. Every tick is stored whole - the
briefing, the prompt, the raw answer, tokens, latency, outcome - in
`sim_decisions`, because how the decision was made is part of the data.

WHAT THIS IS EVIDENCE OF, AND WHAT IT IS NOT. A persona choosing "buy 2
NVDA at 2 PM Saturday" says nothing about markets: Monday's price does
not care who ordered. What the population produces is evidence about the
ENGINE - many concurrent trades, real reserves against real true-ups at
real sizes, breaches, lock conflicts, a settlement run with dozens of open
rows - and, under ADR-025, the shadow hedge's cost per trade.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import alpaca
import err
import groq
import sessions
import weekend
from config import settings
from models import SimDecision, SimUser, TokenPrice, WeekendTrade

# Per decision. The persona is told this cap; the engine's own weekend cap
# (1,000 shares) still applies on top.
MAX_NOTIONAL_USD = Decimal("10000")
MAX_QTY = Decimal("100")
# Pacing, from Groq's free plan (8K tokens a minute, 200K a day; a decision
# is about 2K tokens): personas take turns in two groups, one group per
# hourly tick, 20 seconds apart. Each persona therefore decides every two
# hours - about 100 decisions a day for the eight of them, under the cap
# with room for retries. Raise the cadence when the plan is upgraded.
USER_DELAY_SECONDS = 20
GROUPS = 2

PERSONAS: list[dict] = [
    {
        "slug": "maya",
        "name": "Maya",
        "watchlist": "NVDA,TSLA,COIN,MSTR,HOOD",
        "persona": (
            "You are Maya, 27, a momentum trader. You buy what is already moving up over the last "
            "24 hours and sell what has turned down. You trade often, in sizes of a few thousand "
            "dollars, and you dislike sitting in cash. You cut losers quickly."
        ),
    },
    {
        "slug": "walter",
        "name": "Walter",
        "watchlist": "AAPL,MSFT,GOOGL,AMZN,MCD",
        "persona": (
            "You are Walter, 61, a patient value investor. You buy large, familiar companies only "
            "after a dip of a percent or more from where they were, in round lots you plan to hold "
            "for years. You almost never sell. Most of the time the right answer is to do nothing."
        ),
    },
    {
        "slug": "dev",
        "name": "Dev",
        "watchlist": "GME,MSTR,COIN,CRCL,TSLA",
        "persona": (
            "You are Dev, 22, a high-risk trader who loves volatile names and odd hours. You take "
            "big swings - up to your full cap - on gut feel and recent moves, and you flip positions "
            "within a day. You are comfortable trading at 3 AM on a Sunday."
        ),
    },
    {
        "slug": "priya",
        "name": "Priya",
        "watchlist": "SPY,QQQ,GLD,AAPL",
        "persona": (
            "You are Priya, 38, an index investor. You keep a target mix - about half SPY, a third "
            "QQQ, the rest GLD - and trade only to rebalance toward it when something drifts more "
            "than a few percent off target. You care about paying a fair price and avoid wide "
            "spreads."
        ),
    },
    {
        "slug": "ken",
        "name": "Ken",
        "watchlist": "META,NVDA,AVGO,AMZN,MSFT",
        "persona": (
            "You are Ken, 45, a contrarian. You sell into strength and buy into weakness: a name "
            "up sharply since Friday's close is something to trim, one down sharply is something "
            "to add to. Moderate sizes. You are suspicious of moves with no news behind them."
        ),
    },
    {
        "slug": "lena",
        "name": "Lena",
        "watchlist": "MSFT,AAPL,SPY,QQQ,NVDA",
        "persona": (
            "You are Lena, 33, and you care about execution cost above all. You only trade when "
            "the bid-ask spread is tight and the reserve is small relative to the trade, and you "
            "prefer the most liquid names. When the spread is wide you wait, and you say so."
        ),
    },
    {
        "slug": "omar",
        "name": "Omar",
        "watchlist": "GOOGL,META,HOOD,TSLA,AVGO",
        "persona": (
            "You are Omar, 29, a weekend trader. The whole point, for you, is being able to act "
            "when the stock market is closed: you react to how the token has moved since Friday's "
            "close and position ahead of Monday's open. You like to have a couple of open weekend "
            "trades at a time, in mid-sized amounts."
        ),
    },
    {
        "slug": "sam",
        "name": "Sam",
        "watchlist": "NVDA,TSLA,AAPL,MSTR,GLD",
        "persona": (
            "You are Sam, 50, a mean-reversion trader. Over a weekend you sell what has run up "
            "since Friday's close and buy what has dropped, expecting Monday to pull prices back "
            "toward Friday. You size by how far the price has strayed; small moves are not worth "
            "the reserve."
        ),
    },
]

RULES = """
HOW TRADING WORKS RIGHT NOW
- Session "weekend": the stock market is closed. Your order goes through the ERR engine. A sell is priced at
  the token's executable bid on Jupiter and you are paid that cash immediately; a buy is priced at the ask
  and you pay immediately. A reserve (the "reserve_pct" shown per symbol) is held from your cash until Monday.
  When the market reopens your trade is settled at the real opening price: you end up at MONDAY'S price, not
  the weekend quote, and the reserve comes back adjusted by the difference. If the price moves against you by
  more than the reserve you owe the excess. Buys need cash for the notional plus the reserve.
- Session "regular": a normal market order at the broker, filled at the market.
- Session "premarket" or "afterhours": a limit order at the broker in the extended session, whole shares only.
- Session "overnight": you cannot trade in this window. Answer "hold".
- Shares already committed to an open weekend trade cannot be sold again until it settles.

YOUR LIMITS
- One decision per briefing: exactly one symbol, or hold.
- Maximum {max_notional} USD and {max_qty} shares per decision. Only symbols on your watchlist.
- Sells: you may only sell shares you hold and that are not committed. Buys: only with cash you have.
- Holding is a real choice. Do not trade for the sake of trading; trade when your style says so.

ANSWER FORMAT
Reply with ONE JSON object and nothing else:
{{"action": "buy" | "sell" | "hold", "symbol": "NVDA" | null, "qty": number | null, "reason": "one or two sentences", "confidence": 0.0-1.0}}
qty may be fractional in the weekend and regular sessions; whole shares elsewhere.
"""

_CENT = Decimal("0.01")


def _pct(new: Decimal | None, old: Decimal | None) -> str | None:
    if new is None or old is None or old == 0:
        return None
    return format(((new - old) / old * 100).quantize(_CENT), "f")


def _fmt(value: Decimal | None, places: str = "0.01") -> str | None:
    return None if value is None else format(value.quantize(Decimal(places)), "f")


# ---------------------------------------------------------------------------
# The briefing
# ---------------------------------------------------------------------------


def _latest_rows(session: Session, token_symbol: str, since: dt.datetime) -> list[TokenPrice]:
    rows = session.execute(
        select(TokenPrice)
        .where(TokenPrice.symbol == token_symbol, TokenPrice.sampled_at >= since)
        .order_by(TokenPrice.sampled_at.desc())
    ).scalars()
    return list(rows)


def price_context(session: Session, underlying: str, now: dt.datetime | None = None) -> dict | None:
    """What a trader would want to know about one symbol, from the sampler's
    rows: token price now, moves over 1h / 24h / since the last regular-hours
    print, the executable spread, and this symbol's reserve percentage."""
    now = now or dt.datetime.now(dt.timezone.utc)
    token_symbol = f"{underlying}x"
    rows = _latest_rows(session, token_symbol, now - dt.timedelta(hours=26))
    if not rows:
        return None
    latest = rows[0]

    def at_or_before(moment: dt.datetime) -> TokenPrice | None:
        for row in rows:
            if row.sampled_at <= moment:
                return row
        return None

    hour_ago = at_or_before(now - dt.timedelta(hours=1))
    day_ago = at_or_before(now - dt.timedelta(hours=24))
    last_open = next((row for row in rows if row.market_open and row.market_price), None)
    spread_pct = None
    if latest.bid_usd and latest.ask_usd and latest.bid_usd > 0:
        mid = (latest.bid_usd + latest.ask_usd) / 2
        spread_pct = format(((latest.ask_usd - latest.bid_usd) / mid * 100).quantize(Decimal("0.001")), "f")
    reserve_pct = None
    try:
        sizing = err.compute(underlying, Decimal("1"), latest.usd_price)
        reserve_pct = format((sizing["reserve"] / latest.usd_price * 100).quantize(_CENT), "f")
    except (KeyError, InvalidOperation, ArithmeticError):
        pass
    return {
        "symbol": underlying,
        "token": token_symbol,
        "token_price": _fmt(latest.usd_price),
        "bid": _fmt(latest.bid_usd),
        "ask": _fmt(latest.ask_usd),
        "spread_pct": spread_pct,
        "change_1h_pct": _pct(latest.usd_price, hour_ago.usd_price if hour_ago else None),
        "change_24h_pct": _pct(latest.usd_price, day_ago.usd_price if day_ago else None),
        "last_market_price": _fmt(last_open.market_price) if last_open else None,
        "change_since_market_pct": _pct(latest.usd_price, last_open.market_price if last_open else None),
        "reserve_pct": reserve_pct,
        "as_of": latest.sampled_at.isoformat(timespec="minutes"),
    }


def briefing(session: Session, user: SimUser, live_session: str, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    account = alpaca.get_trading_account(user.alpaca_account_id)
    positions = alpaca.list_positions(user.alpaca_account_id)
    open_trades = session.execute(
        select(WeekendTrade).where(
            WeekendTrade.alpaca_account_id == user.alpaca_account_id,
            WeekendTrade.state.in_(weekend.OPEN_STATES),
        )
    ).scalars()
    watch = [s.strip().upper() for s in user.watchlist.split(",") if s.strip()]
    return {
        "now_eastern": now.astimezone(sessions.ET).strftime("%A %Y-%m-%d %H:%M"),
        "session": live_session,
        "cash": str(account.get("cash")),
        "positions": [
            {
                "symbol": p.get("symbol"),
                "qty": p.get("qty"),
                "available_qty": p.get("qty_available") or p.get("qty"),
                "avg_cost": p.get("avg_entry_price"),
                "unrealized_pl_pct": p.get("unrealized_plpc"),
            }
            for p in positions
        ],
        "open_weekend_trades": [
            {
                "symbol": t.symbol,
                "side": t.side,
                "qty": format(t.qty.normalize(), "f"),
                "price": _fmt(t.p_open),
                "state": t.state,
            }
            for t in open_trades
        ],
        "watchlist": [ctx for s in watch if (ctx := price_context(session, s, now)) is not None],
    }


def prompt_for(user: SimUser) -> str:
    return (
        user.persona
        + "\n"
        + RULES.format(max_notional=format(MAX_NOTIONAL_USD, "f"), max_qty=format(MAX_QTY, "f"))
    )


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------


class Intent:
    def __init__(self, action: str, symbol: str | None, qty: Decimal | None, reason: str, confidence: Decimal | None):
        self.action = action
        self.symbol = symbol
        self.qty = qty
        self.reason = reason
        self.confidence = confidence


def parse_intent(raw: str, watchlist: list[str]) -> Intent:
    """The model's JSON, checked. Anything malformed or out of bounds raises
    ValueError with a reason that is recorded on the decision."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    action = str(data.get("action") or "").lower()
    if action not in ("buy", "sell", "hold"):
        raise ValueError(f"action must be buy, sell or hold; got {action!r}")
    reason = str(data.get("reason") or "")[:1000]
    confidence = None
    try:
        if data.get("confidence") is not None:
            confidence = Decimal(str(data["confidence"])).quantize(_CENT)
    except InvalidOperation:
        confidence = None
    if action == "hold":
        return Intent("hold", None, None, reason, confidence)
    symbol = str(data.get("symbol") or "").upper().strip()
    if symbol not in watchlist:
        raise ValueError(f"symbol {symbol!r} is not on the watchlist")
    try:
        qty = Decimal(str(data.get("qty")))
    except InvalidOperation:
        raise ValueError(f"qty {data.get('qty')!r} is not a number") from None
    if not qty.is_finite() or qty <= 0:
        raise ValueError("qty must be positive")
    if qty > MAX_QTY:
        raise ValueError(f"qty {qty} is over the cap of {MAX_QTY}")
    qty = qty.quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    if qty <= 0:
        raise ValueError("qty rounds to zero")
    return Intent(action, symbol, qty, reason, confidence)


# ---------------------------------------------------------------------------
# Acting on it
# ---------------------------------------------------------------------------


def _notional_guard(symbol: str, qty: Decimal, price: Decimal | None) -> None:
    if price is not None and qty * price > MAX_NOTIONAL_USD:
        raise HTTPException(
            status_code=400,
            detail=f"over_cap: {format(qty, 'f')} {symbol} at about {format(price, '.2f')} exceeds the {format(MAX_NOTIONAL_USD, 'f')} USD cap",
        )


def execute(session: Session, user: SimUser, intent: Intent, live_session: str, brief: dict) -> tuple[str, str | None]:
    """Route the intent the way a person's order would go. Returns
    (outcome, ref) - see SimDecision for the vocabulary."""
    if intent.action == "hold":
        return "hold", None
    if live_session == sessions.OVERNIGHT:
        return "skipped", None
    assert intent.symbol is not None and intent.qty is not None
    ctx = next((c for c in brief.get("watchlist", []) if c["symbol"] == intent.symbol), None)
    price = Decimal(ctx["token_price"]) if ctx and ctx.get("token_price") else None
    _notional_guard(intent.symbol, intent.qty, price)

    if live_session == sessions.WEEKEND:
        trade = weekend.open_trade(
            session,
            user_id=f"sim_{user.slug}",
            account_id=user.alpaca_account_id,
            symbol=intent.symbol,
            side=intent.action,
            qty=intent.qty,
            source="sim",
        )
        return "weekend_trade", str(trade.id)

    payload: dict = {"symbol": intent.symbol, "side": intent.action, "time_in_force": "day"}
    if live_session == sessions.REGULAR:
        payload["type"] = "market"
        payload["qty"] = format(intent.qty.normalize(), "f")
    else:
        whole = intent.qty.to_integral_value(rounding=ROUND_DOWN)
        if whole <= 0:
            raise HTTPException(status_code=400, detail="extended_hours_needs_whole_shares")
        payload["type"] = "limit"
        payload["qty"] = format(whole, "f")
        payload["limit_price"] = format(weekend._marketable_limit(intent.symbol, intent.action), "f")
        payload["extended_hours"] = True
    try:
        order = alpaca.create_order(user.alpaca_account_id, payload)
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc
    return "order", str(order.get("id") or "")


# ---------------------------------------------------------------------------
# One tick
# ---------------------------------------------------------------------------


def active_users(session: Session) -> list[SimUser]:
    return list(session.execute(select(SimUser).where(SimUser.active).order_by(SimUser.id)).scalars())


def decide(session: Session, user: SimUser, live_session: str, *, write: bool) -> SimDecision:
    """Brief, ask, act, record - for one persona."""
    brief = briefing(session, user, live_session)
    system = prompt_for(user)
    user_msg = "BRIEFING\n" + json.dumps(brief, indent=1) + "\n\nDecide now. JSON only."
    decision = SimDecision(
        sim_user_id=user.id,
        session=live_session,
        model=user.model,
        briefing=json.dumps(brief),
        prompt=system + "\n\n" + user_msg,
        outcome="error",
    )
    if not write:
        decision.error = "dry run"
        return decision

    try:
        answer = groq.complete(system, user_msg, model=user.model)
    except groq.GroqError as exc:
        decision.error = exc.message[:1000]
        session.add(decision)
        session.commit()
        return decision
    decision.raw_output = answer["content"]
    decision.model = answer["model"]
    decision.latency_ms = answer["latency_ms"]
    decision.prompt_tokens = answer["prompt_tokens"]
    decision.completion_tokens = answer["completion_tokens"]

    watch = [s.strip().upper() for s in user.watchlist.split(",") if s.strip()]
    try:
        intent = parse_intent(answer["content"], watch)
    except ValueError as exc:
        decision.error = f"unusable answer: {exc}"[:1000]
        session.add(decision)
        session.commit()
        return decision
    decision.action = intent.action
    decision.symbol = intent.symbol
    decision.qty = intent.qty
    decision.reason = intent.reason
    decision.confidence = intent.confidence

    try:
        outcome, ref = execute(session, user, intent, live_session, brief)
        decision.outcome = outcome
        decision.ref = ref
    except HTTPException as exc:
        session.rollback()
        decision.outcome = "refused"
        decision.error = str(exc.detail)[:1000]
    session.add(decision)
    session.commit()
    return decision


def group_for(now: dt.datetime | None = None) -> int:
    """Which group's turn it is: the hour's parity."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.hour % GROUPS


def tick(session: Session, *, write: bool, everyone: bool = False) -> dict:
    """This hour's group of personas decides once (all of them with
    `everyone`). Returns a tally and a log."""
    live = sessions.effective_session()["session"]
    summary: dict = {"session": live, "users": 0, "log": [], "outcomes": {}}
    if write and not groq.configured():
        summary["log"].append("GROQ_API_KEY is not set; no persona can decide")
        return summary
    group = group_for()
    users = [u for u in active_users(session) if everyone or u.id % GROUPS == group]
    for index, user in enumerate(users):
        summary["users"] += 1
        if write and index:
            time.sleep(USER_DELAY_SECONDS)
        try:
            decision = decide(session, user, live, write=write)
        except (alpaca.AlpacaError, HTTPException) as exc:
            session.rollback()
            message = getattr(exc, "detail", None) or getattr(exc, "message", str(exc))
            summary["log"].append(f"{user.name}: briefing failed - {message}")
            summary["outcomes"]["error"] = summary["outcomes"].get("error", 0) + 1
            continue
        summary["outcomes"][decision.outcome] = summary["outcomes"].get(decision.outcome, 0) + 1
        what = decision.action or "-"
        if decision.symbol:
            what += f" {format(decision.qty.normalize(), 'f') if decision.qty else ''} {decision.symbol}"
        line = f"{user.name}: {what} -> {decision.outcome}"
        if decision.ref:
            line += f" ({decision.ref})"
        if decision.error:
            line += f" - {decision.error[:120]}"
        summary["log"].append(line)
        if decision.error and "HTTP 429" in decision.error:
            # The plan's limit: stop the tick rather than burn the rest of
            # the group's turn on refusals. The next hour tries again.
            summary["log"].append("rate limited by Groq; stopping this tick")
            break
    return summary


# ---------------------------------------------------------------------------
# Provisioning: real sandbox accounts for the personas
# ---------------------------------------------------------------------------

_ACTIVATION_TRIES = 30
_ACTIVATION_WAIT_SECONDS = 2


def _wait_active(account_id: str) -> str:
    status = ""
    for _ in range(_ACTIVATION_TRIES):
        status = str(alpaca.get_account(account_id).get("status", ""))
        if status == "ACTIVE":
            return status
        time.sleep(_ACTIVATION_WAIT_SECONDS)
    return status


def provision(session: Session, *, cash: Decimal, model: str | None = None) -> list[SimUser]:
    """Create the missing personas: an Alpaca account each, funded from the
    firm account. Idempotent: a persona that exists is left alone."""
    created: list[SimUser] = []
    for spec in PERSONAS:
        existing = session.execute(select(SimUser).where(SimUser.slug == spec["slug"])).scalar_one_or_none()
        if existing is not None:
            continue
        email = f"sim-{spec['slug']}@yagnum.invalid"
        account = alpaca.find_account_by_email(email)
        if account is None:
            account = alpaca.create_account(email, spec["name"], "Sim")
        account_id = str(account["id"])
        status = _wait_active(account_id)
        print(f"[sim] {spec['name']}: account {account_id[:8]} {status}", file=sys.stderr)
        if status == "ACTIVE" and cash > 0:
            alpaca.fund_account(account_id, cash, f"{spec['name']} Sim")
        user = SimUser(
            slug=spec["slug"],
            name=spec["name"],
            persona=spec["persona"],
            watchlist=spec["watchlist"],
            alpaca_account_id=account_id,
            model=model or settings.groq_model,
        )
        session.add(user)
        session.commit()
        created.append(user)
    return created


def seed_positions(session: Session, user: SimUser, notional: Decimal) -> list[dict]:
    """Give a fresh persona something to sell: `notional` split across the
    first three names on its watchlist, whole shares, in whatever order the
    hour allows. Returns the orders placed."""
    live = sessions.effective_session()["session"]
    if live in (sessions.WEEKEND, sessions.OVERNIGHT):
        return []
    names = [s.strip().upper() for s in user.watchlist.split(",") if s.strip()][:3]
    per_name = notional / len(names)
    placed = []
    for symbol in names:
        last = Decimal(str(alpaca.latest_trade(symbol).get("p") or "0"))
        if last <= 0:
            continue
        qty = (per_name / last).to_integral_value(rounding=ROUND_DOWN)
        if qty <= 0:
            continue
        payload: dict = {"symbol": symbol, "side": "buy", "qty": format(qty, "f"), "time_in_force": "day"}
        if live == sessions.REGULAR:
            payload["type"] = "market"
        else:
            payload["type"] = "limit"
            payload["limit_price"] = format(weekend._marketable_limit(symbol, "buy"), "f")
            payload["extended_hours"] = True
        order = alpaca.create_order(user.alpaca_account_id, payload)
        placed.append({"symbol": symbol, "qty": format(qty, "f"), "order_id": order.get("id"), "status": order.get("status")})
    return placed
