"""The ERR engine and the weekend simulator (ADR-018, ADR-019).

Three layers, tested separately:

    sessions.py   pure calendar maths - fixed moments in ET, no mocks
    err.py        the reserve formula against hand-computed Decimals
    the engine    open -> settle through the real routes, with Alpaca and
                  Jupiter replaced by fakes that record every journal and
                  order, so each test can assert on the exact cash moves
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

import alpaca
import err
import jupiter
import sessions
import weekend
from config import settings

ET = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def clean_override():
    """No test leaves the simulator switched on for the next one."""
    yield
    sessions._simulate_weekend = False


# ---------------------------------------------------------------------------
# sessions.py - the calendar
# ---------------------------------------------------------------------------


def _at(day: int, hour: int, minute: int) -> dt.datetime:
    """A moment in ET during the week of Mon 2026-08-24 (day 0 = Monday)."""
    return dt.datetime(2026, 8, 24 + day, hour, minute, tzinfo=ET)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (_at(0, 3, 59), sessions.OVERNIGHT),  # Monday 3:59 AM
        (_at(0, 4, 0), sessions.PREMARKET),  # Monday 4:00 AM
        (_at(0, 9, 29), sessions.PREMARKET),
        (_at(0, 9, 30), sessions.REGULAR),
        (_at(0, 15, 59), sessions.REGULAR),
        (_at(0, 16, 0), sessions.AFTERHOURS),
        (_at(0, 19, 59), sessions.AFTERHOURS),
        (_at(0, 20, 0), sessions.OVERNIGHT),  # Monday 8 PM: a weeknight
        (_at(4, 19, 59), sessions.AFTERHOURS),  # Friday 7:59 PM
        (_at(4, 20, 0), sessions.WEEKEND),  # Friday 8 PM: the dead zone opens
        (_at(5, 12, 0), sessions.WEEKEND),  # Saturday noon
        (_at(6, 19, 59), sessions.WEEKEND),  # Sunday 7:59 PM
        (_at(6, 20, 0), sessions.OVERNIGHT),  # Sunday 8 PM: 24/5 reopens
    ],
)
def test_scheduled_session(moment, expected):
    assert sessions.scheduled_session(moment) == expected


def test_scheduled_session_handles_utc_input():
    # Saturday 01:00 UTC is Friday 9 PM ET - inside the weekend.
    moment = dt.datetime(2026, 8, 29, 1, 0, tzinfo=dt.timezone.utc)
    assert sessions.scheduled_session(moment) == sessions.WEEKEND


def test_override_flips_only_in_development(monkeypatch):
    sessions.set_weekend_override(True)
    state = sessions.effective_session(_at(0, 13, 0))  # Monday 1 PM
    assert state == {"session": "weekend", "scheduled": "regular", "simulated": True}

    # The same flag is inert in production, whatever it holds.
    monkeypatch.setattr(settings, "app_env", "production")
    assert sessions.weekend_override() is False
    with pytest.raises(RuntimeError):
        sessions.set_weekend_override(True)


def test_override_on_a_real_weekend_is_not_simulated():
    sessions.set_weekend_override(True)
    state = sessions.effective_session(_at(5, 12, 0))  # Saturday
    assert state["session"] == "weekend"
    assert state["simulated"] is False


# ---------------------------------------------------------------------------
# err.py - the reserve
# ---------------------------------------------------------------------------


def test_reserve_uses_measured_sigma_and_pooled_z():
    sizing = err.compute("NVDA", Decimal("10"), Decimal("226"))
    assert sizing["sigma"] == Decimal("0.0270")
    assert sizing["sigma_source"] == "measured"
    assert sizing["z"] == Decimal("3.7759")
    # 10 * 226 * 0.0270 * 3.7759 = 230.405418, ceiling to the cent.
    assert sizing["reserve"] == Decimal("230.41")


def test_reserve_rounds_up_never_down():
    sizing = err.compute("MCD", Decimal("1"), Decimal("100"))
    # 100 * 0.0071 * 3.7759 = 2.6808... -> 2.69, not 2.68.
    assert sizing["reserve"] == Decimal("2.69")


def test_unmeasured_symbol_falls_back_to_pooled_sigma():
    sizing = err.compute("ZZZZ", Decimal("1"), Decimal("100"))
    assert sizing["sigma"] == Decimal("0.0251")
    assert sizing["sigma_source"] == "pooled_fallback"


# ---------------------------------------------------------------------------
# Fakes for the engine tests
# ---------------------------------------------------------------------------

NVDAX = {
    "symbol": "NVDAx",
    "underlying": "NVDA",
    "mint": "MintNVDAx",
    "name": "NVIDIA xStock",
    "decimals": 8,
}


class Broker:
    """A fake Alpaca that records journals and orders and can be scripted."""

    def __init__(self):
        self.journals: list[dict] = []
        self.orders: list[dict] = []
        self.order_status = "filled"
        self.filled_avg_price = "195"
        self.positions = [{"symbol": "NVDA", "qty": "5", "qty_available": "5"}]
        self.cash = "100000"
        self.last_trade_price = "200"

    def install(self, monkeypatch):
        monkeypatch.setattr(settings, "alpaca_firm_account_id", "firm-0001")
        monkeypatch.setattr(alpaca, "list_positions", lambda account_id: self.positions)
        monkeypatch.setattr(
            alpaca, "get_trading_account", lambda account_id: {"cash": self.cash}
        )
        monkeypatch.setattr(alpaca, "latest_trade", lambda symbol: {"p": self.last_trade_price})
        monkeypatch.setattr(alpaca, "create_journal", self._create_journal)
        monkeypatch.setattr(alpaca, "create_order", self._create_order)
        monkeypatch.setattr(alpaca, "get_order", self._get_order)
        monkeypatch.setattr(weekend, "_FILL_POLL_SECONDS", 0)
        monkeypatch.setattr(
            jupiter, "xstock_for", lambda underlying: NVDAX if underlying == "NVDA" else None
        )
        monkeypatch.setattr(jupiter, "executable_price", self._executable_price)

    def _create_journal(self, from_account, to_account, amount, *, description=None):
        entry = {
            "from": from_account,
            "to": to_account,
            "amount": format(amount, "f"),
            "description": description,
        }
        self.journals.append(entry)
        return {"id": f"jnl-{len(self.journals)}"}

    def _create_order(self, account_id, payload):
        self.orders.append(payload)
        return {"id": f"ord-{len(self.orders)}", "status": "accepted"}

    def _get_order(self, account_id, order_id):
        return {
            "id": order_id,
            "status": self.order_status,
            "filled_avg_price": self.filled_avg_price if self.order_status == "filled" else None,
        }

    def _executable_price(self, token, side, qty):
        return {
            "price": Decimal("200"),
            "usd_amount": Decimal("200") * qty,
            "token_amount": qty,
            "price_impact_pct": "0.01",
        }


@pytest.fixture
def broker(monkeypatch):
    fake = Broker()
    fake.install(monkeypatch)
    return fake


def _open_sell(client, qty="2"):
    sessions.set_weekend_override(True)
    response = client.post("/weekend/orders", json={"symbol": "NVDA", "side": "sell", "qty": qty})
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------


def test_open_sell_reserves_escrow_and_advances_cash(db_client, broker):
    trade = _open_sell(db_client)

    assert trade["state"] == "provisional"
    assert trade["simulated"] is True
    assert trade["p_open"] == "200"
    # 2 * 200 * 0.0270 * 3.7759 = 40.779... -> ceiling 40.78.
    assert trade["reserve"] == "40.78"

    # Two journals, tagged: the escrow in, the advance out.
    assert broker.journals[0]["from"] == "acct-test-0001"
    assert broker.journals[0]["to"] == "firm-0001"
    assert broker.journals[0]["amount"] == "40.78"
    assert "ERR escrow" in broker.journals[0]["description"]
    assert broker.journals[1]["from"] == "firm-0001"
    assert broker.journals[1]["to"] == "acct-test-0001"
    assert broker.journals[1]["amount"] == "400.00"
    assert "ERR advance" in broker.journals[1]["description"]


def test_open_needs_the_weekend(db_client, broker):
    # No override, and no test runs on a real weekend... but the calendar
    # might disagree, so force the scheduled session to a weekday one.
    response = db_client.post(
        "/weekend/orders", json={"symbol": "NVDA", "side": "sell", "qty": "1"}
    )
    if sessions.scheduled_session() != sessions.WEEKEND:
        assert response.status_code == 409
        assert "market_is_open" in response.json()["detail"]


def test_open_sell_needs_the_shares(db_client, broker):
    broker.positions = [{"symbol": "NVDA", "qty": "1", "qty_available": "1"}]
    sessions.set_weekend_override(True)
    response = db_client.post(
        "/weekend/orders", json={"symbol": "NVDA", "side": "sell", "qty": "2"}
    )
    assert response.status_code == 400
    assert "insufficient_shares" in response.json()["detail"]


def test_open_buy_charges_notional_plus_reserve(db_client, broker):
    sessions.set_weekend_override(True)
    response = db_client.post(
        "/weekend/orders", json={"symbol": "NVDA", "side": "buy", "qty": "2"}
    )
    assert response.status_code == 200, response.text
    # Escrow in, then the purchase charge in - both toward the firm.
    assert [j["to"] for j in broker.journals] == ["firm-0001", "firm-0001"]
    assert broker.journals[1]["amount"] == "400.00"


def test_open_buy_needs_the_cash(db_client, broker):
    broker.cash = "100"
    sessions.set_weekend_override(True)
    response = db_client.post(
        "/weekend/orders", json={"symbol": "NVDA", "side": "buy", "qty": "2"}
    )
    assert response.status_code == 400
    assert "insufficient_cash" in response.json()["detail"]


def test_fractional_weekend_orders_are_refused(db_client, broker):
    sessions.set_weekend_override(True)
    response = db_client.post(
        "/weekend/orders", json={"symbol": "NVDA", "side": "sell", "qty": "1.5"}
    )
    assert response.status_code == 422
    assert "whole_shares_only" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Settlement: injected gaps (the dev knob)
# ---------------------------------------------------------------------------


def test_injected_gap_settles_with_true_up(db_client, broker):
    trade = _open_sell(db_client)
    broker.journals.clear()

    response = db_client.post(
        f"/weekend/orders/{trade['id']}/settle", json={"mode": "injected", "gap": "-0.05"}
    )
    assert response.status_code == 200, response.text
    settled = response.json()

    # p_close = 200 * 0.95 = 190; true-up = 2 * (190 - 200) = -20;
    # released = 40.78 - 20 = 20.78. The trader ended at the Monday price.
    assert settled["state"] == "settled"
    assert settled["p_close"] == "190"
    assert settled["true_up"] == "-20"
    assert settled["escrow_returned"] == "20.78"
    assert settled["shortfall"] is None

    # Injected mode moves only the escrow: one journal, firm -> trader.
    assert len(broker.journals) == 1
    assert broker.journals[0]["from"] == "firm-0001"
    assert broker.journals[0]["amount"] == "20.78"
    kinds = [event["kind"] for event in settled["events"]]
    assert "gap_injected" in kinds and "escrow_released" in kinds
    assert "hedge_swept" not in kinds


def test_injected_gap_beyond_the_reserve_breaches(db_client, broker):
    trade = _open_sell(db_client)
    broker.journals.clear()

    response = db_client.post(
        f"/weekend/orders/{trade['id']}/settle", json={"mode": "injected", "gap": "-0.2"}
    )
    settled = response.json()

    # true-up = 2 * (160 - 200) = -80 > the 40.78 reserve: breached, and the
    # 39.22 excess is debited - collateral, not a cap (ADR-017).
    assert settled["state"] == "breached"
    assert settled["escrow_returned"] == "0"
    assert settled["shortfall"] == "39.22"
    assert broker.journals[0]["from"] == "acct-test-0001"
    assert broker.journals[0]["amount"] == "39.22"
    assert "shortfall" in broker.journals[0]["description"]


def test_injected_mode_requires_a_gap_and_development(db_client, broker, monkeypatch):
    trade = _open_sell(db_client)
    response = db_client.post(f"/weekend/orders/{trade['id']}/settle", json={"mode": "injected"})
    assert response.status_code == 422

    monkeypatch.setattr(settings, "app_env", "production")
    response = db_client.post(
        f"/weekend/orders/{trade['id']}/settle", json={"mode": "injected", "gap": "-0.05"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Settlement: the real hedge
# ---------------------------------------------------------------------------


def test_market_settlement_in_regular_hours(db_client, broker, monkeypatch):
    trade = _open_sell(db_client)
    broker.journals.clear()
    monkeypatch.setattr(sessions, "scheduled_session", lambda now=None: sessions.REGULAR)

    response = db_client.post(f"/weekend/orders/{trade['id']}/settle", json={"mode": "market"})
    assert response.status_code == 200, response.text
    settled = response.json()

    # A market order in the open session, filled at 195.
    assert broker.orders[0]["type"] == "market"
    assert "extended_hours" not in broker.orders[0]
    assert settled["state"] == "settled"
    assert settled["p_close"] == "195"
    # Sweep 2*195 = 390 to the firm, then release 40.78 - 10 = 30.78.
    assert broker.journals[0]["to"] == "firm-0001"
    assert broker.journals[0]["amount"] == "390.00"
    assert broker.journals[1]["from"] == "firm-0001"
    assert broker.journals[1]["amount"] == "30.78"
    assert settled["escrow_returned"] == "30.78"


def test_market_settlement_after_hours_uses_marketable_limit(db_client, broker, monkeypatch):
    trade = _open_sell(db_client)
    monkeypatch.setattr(sessions, "scheduled_session", lambda now=None: sessions.AFTERHOURS)
    broker.order_status = "accepted"  # extended-hours limits may not fill fast

    response = db_client.post(f"/weekend/orders/{trade['id']}/settle", json={"mode": "market"})
    assert response.status_code == 200, response.text
    pending = response.json()

    order = broker.orders[0]
    assert order["type"] == "limit"
    assert order["extended_hours"] is True
    assert order["time_in_force"] == "day"
    # Sell priced 0.5% under the 200 last trade: marketable.
    assert order["limit_price"] == "199.00"
    assert pending["state"] == "awaiting_settlement"

    # The fill lands later; settling again completes the reconciliation.
    broker.order_status = "filled"
    response = db_client.post(f"/weekend/orders/{trade['id']}/settle", json={"mode": "market"})
    assert response.json()["state"] == "settled"


def test_market_settlement_refused_inside_a_real_weekend(db_client, broker, monkeypatch):
    trade = _open_sell(db_client)
    monkeypatch.setattr(sessions, "scheduled_session", lambda now=None: sessions.WEEKEND)
    response = db_client.post(f"/weekend/orders/{trade['id']}/settle", json={"mode": "market"})
    assert response.status_code == 409
    assert "market_closed" in response.json()["detail"]


def test_settling_a_settled_trade_conflicts(db_client, broker):
    trade = _open_sell(db_client)
    db_client.post(f"/weekend/orders/{trade['id']}/settle", json={"mode": "injected", "gap": "0"})
    response = db_client.post(
        f"/weekend/orders/{trade['id']}/settle", json={"mode": "injected", "gap": "0"}
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# The dev clock and the simulated market clock
# ---------------------------------------------------------------------------


def test_dev_clock_flips_the_session(db_client, broker):
    response = db_client.post("/dev/clock", json={"simulate_weekend": True})
    assert response.status_code == 200
    body = response.json()
    assert body["session"] == "weekend"
    assert body["weekend_trading"] is True
    assert body["dev_toggle"] is True

    response = db_client.post("/dev/clock", json={"simulate_weekend": False})
    assert response.json()["session"] == sessions.scheduled_session()


def test_dev_clock_does_not_exist_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    response = client.post("/dev/clock", json={"simulate_weekend": True})
    assert response.status_code == 404


def test_market_clock_reports_the_simulation(client, monkeypatch):
    monkeypatch.setattr(
        alpaca,
        "get_clock",
        lambda: {"is_open": True, "next_open": "n", "next_close": "c", "timestamp": "t"},
    )
    sessions.set_weekend_override(True)
    body = client.get("/market/clock").json()
    assert body["is_open"] is False
    assert body["simulated"] is True

    sessions.set_weekend_override(False)
    body = client.get("/market/clock").json()
    assert body["is_open"] is True
    assert body["simulated"] is False


# ---------------------------------------------------------------------------
# Extended-hours pass-through on ordinary orders
# ---------------------------------------------------------------------------


def test_extended_hours_needs_a_day_limit_order(client):
    response = client.post(
        "/orders",
        json={"symbol": "NVDA", "qty": "1", "side": "buy", "type": "market", "extended_hours": True},
    )
    assert response.status_code == 422


def test_extended_hours_reaches_alpaca(client, monkeypatch):
    sent = {}

    def create_order(account_id, payload):
        sent.update(payload)
        return {"id": "ord-1", "status": "accepted", **payload}

    monkeypatch.setattr(alpaca, "create_order", create_order)
    response = client.post(
        "/orders",
        json={
            "symbol": "NVDA",
            "qty": "1",
            "side": "buy",
            "type": "limit",
            "limit_price": "1.00",
            "extended_hours": True,
        },
    )
    assert response.status_code == 200, response.text
    assert sent["extended_hours"] is True
    assert response.json()["extended_hours"] is True
