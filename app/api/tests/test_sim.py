"""Simulated traders (ADR-026): the model's answer is checked, then routed
exactly like a person's order. Nothing here reaches Groq, Alpaca, Jupiter
or the chain: every dependency is a fake."""

from decimal import Decimal

import pytest
from fastapi import HTTPException

import alpaca
import groq
import sessions
import sim
import weekend
from models import SimUser

WATCH = ["NVDA", "TSLA"]


def _user() -> SimUser:
    user = SimUser(
        slug="maya",
        name="Maya",
        persona="You are Maya.",
        watchlist="NVDA,TSLA",
        alpaca_account_id="acct-sim-0001",
        model="openai/gpt-oss-120b",
    )
    user.id = 1
    return user


# ---------------------------------------------------------------- parsing ---


def test_parse_hold():
    intent = sim.parse_intent('{"action": "hold", "reason": "nothing to do", "confidence": 0.8}', WATCH)
    assert intent.action == "hold"
    assert intent.symbol is None and intent.qty is None
    assert intent.confidence == Decimal("0.80")


def test_parse_sell_rounds_qty_down_to_thousandths():
    intent = sim.parse_intent('{"action": "sell", "symbol": "nvda", "qty": 2.5559, "reason": "x"}', WATCH)
    assert intent.action == "sell"
    assert intent.symbol == "NVDA"
    assert intent.qty == Decimal("2.555")


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ("not json", "not JSON"),
        ("[1,2]", "not a JSON object"),
        ('{"action": "short", "symbol": "NVDA", "qty": 1}', "action must be"),
        ('{"action": "buy", "symbol": "AAPL", "qty": 1}', "not on the watchlist"),
        ('{"action": "buy", "symbol": "NVDA", "qty": "lots"}', "not a number"),
        ('{"action": "buy", "symbol": "NVDA", "qty": -1}', "must be positive"),
        ('{"action": "buy", "symbol": "NVDA", "qty": 5000}', "over the cap"),
        ('{"action": "buy", "symbol": "NVDA", "qty": 0.0001}', "rounds to zero"),
    ],
)
def test_parse_rejects_bad_answers(raw, fragment):
    with pytest.raises(ValueError) as excinfo:
        sim.parse_intent(raw, WATCH)
    assert fragment in str(excinfo.value)


# ---------------------------------------------------------------- routing ---


def _brief(price="200"):
    return {"watchlist": [{"symbol": "NVDA", "token_price": price}]}


def test_hold_and_overnight_do_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(alpaca, "create_order", lambda account_id, payload: calls.append(payload))
    hold = sim.Intent("hold", None, None, "", None)
    assert sim.execute(None, _user(), hold, sessions.WEEKEND, _brief()) == ("hold", None)
    buy = sim.Intent("buy", "NVDA", Decimal("1"), "", None)
    assert sim.execute(None, _user(), buy, sessions.OVERNIGHT, _brief()) == ("skipped", None)
    assert calls == []


def test_notional_cap_refuses_before_any_order(monkeypatch):
    calls = []
    monkeypatch.setattr(alpaca, "create_order", lambda account_id, payload: calls.append(payload))
    big = sim.Intent("buy", "NVDA", Decimal("100"), "", None)  # 100 x 200 = 20,000 > cap
    with pytest.raises(HTTPException) as excinfo:
        sim.execute(None, _user(), big, sessions.REGULAR, _brief())
    assert "over_cap" in excinfo.value.detail
    assert calls == []


def test_regular_hours_is_a_market_day_order(monkeypatch):
    calls = []

    def create_order(account_id, payload):
        calls.append((account_id, payload))
        return {"id": "ord-1", "status": "accepted"}

    monkeypatch.setattr(alpaca, "create_order", create_order)
    intent = sim.Intent("buy", "NVDA", Decimal("2.5"), "", None)
    assert sim.execute(None, _user(), intent, sessions.REGULAR, _brief()) == ("order", "ord-1")
    account_id, payload = calls[0]
    assert account_id == "acct-sim-0001"
    assert payload == {"symbol": "NVDA", "side": "buy", "time_in_force": "day", "type": "market", "qty": "2.5"}


def test_extended_hours_is_a_marketable_limit_in_whole_shares(monkeypatch):
    calls = []
    monkeypatch.setattr(alpaca, "create_order", lambda a, p: calls.append(p) or {"id": "ord-2"})
    monkeypatch.setattr(alpaca, "latest_trade", lambda symbol: {"p": "200"})
    intent = sim.Intent("sell", "NVDA", Decimal("3.9"), "", None)
    assert sim.execute(None, _user(), intent, sessions.AFTERHOURS, _brief()) == ("order", "ord-2")
    payload = calls[0]
    assert payload["type"] == "limit"
    assert payload["qty"] == "3"
    assert payload["extended_hours"] is True
    assert payload["limit_price"] == "199.00"  # 0.5% under the last trade for a sell


def test_extended_hours_refuses_a_fraction_of_a_share(monkeypatch):
    monkeypatch.setattr(alpaca, "latest_trade", lambda symbol: {"p": "200"})
    intent = sim.Intent("sell", "NVDA", Decimal("0.5"), "", None)
    with pytest.raises(HTTPException) as excinfo:
        sim.execute(None, _user(), intent, sessions.PREMARKET, _brief())
    assert "whole_shares" in excinfo.value.detail


def test_weekend_goes_through_the_engine_tagged_sim(monkeypatch):
    seen = {}

    class Trade:
        id = 42

    def open_trade(session, **kwargs):
        seen.update(kwargs)
        return Trade()

    monkeypatch.setattr(weekend, "open_trade", open_trade)
    intent = sim.Intent("sell", "NVDA", Decimal("2"), "", None)
    assert sim.execute("session", _user(), intent, sessions.WEEKEND, _brief()) == ("weekend_trade", "42")
    assert seen["source"] == "sim"
    assert seen["user_id"] == "sim_maya"
    assert seen["account_id"] == "acct-sim-0001"
    assert seen["side"] == "sell" and seen["qty"] == Decimal("2")


# --------------------------------------------------------------- the tick ---


def test_tick_refuses_to_run_without_a_key(monkeypatch):
    monkeypatch.setattr(sessions, "effective_session", lambda now=None: {"session": sessions.WEEKEND})
    summary = sim.tick(None, write=True)
    assert summary["users"] == 0
    assert any("GROQ_API_KEY" in line for line in summary["log"])


def test_groups_alternate_by_hour():
    import datetime as dt

    even = dt.datetime(2026, 9, 5, 14, 7, tzinfo=dt.timezone.utc)
    odd = dt.datetime(2026, 9, 5, 15, 7, tzinfo=dt.timezone.utc)
    assert sim.group_for(even) == 0
    assert sim.group_for(odd) == 1


def test_groq_client_reports_missing_key():
    with pytest.raises(groq.GroqError) as excinfo:
        groq.complete("system", "user")
    assert "GROQ_API_KEY" in excinfo.value.message
