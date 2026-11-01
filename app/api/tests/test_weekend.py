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
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

import pytest

import alpaca
import db
import err
import jupiter
import sessions
import weekend
from config import settings

ET = ZoneInfo("America/New_York")

# Kept before the autouse fixture below replaces it, for the one test that
# exercises the real calendar parsing.
_REAL_TRADING_DAYS = sessions._trading_days


@pytest.fixture(autouse=True)
def clean_override():
    """No test leaves the simulator switched on for the next one."""
    yield
    sessions._simulate_weekend = False


@pytest.fixture(autouse=True)
def pass_through_design(monkeypatch):
    """The hand-checked v1 flows below run the pass-through design; the
    locked-price tests at the end of the file switch it on themselves."""
    monkeypatch.setattr(settings, "weekend_design", "pass_through")


@pytest.fixture(autouse=True)
def no_calendar_network(monkeypatch):
    """Session routing must never reach Alpaca's calendar from a unit test.

    None = the weekday-arithmetic fallback; the holiday tests below pass an
    explicit `trading_days` set instead.
    """
    monkeypatch.setattr(sessions, "_trading_days", lambda: None)


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


# Labor Day week, 2026: Monday Sep 7 is a market holiday.
_LABOR_WEEK = frozenset(
    dt.date(2026, 9, day) for day in (3, 4, 8, 9, 10, 11)  # trading days only
)


def _labor(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 9, day, hour, minute, tzinfo=ET)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (_labor(7, 13, 0), sessions.WEEKEND),  # holiday Monday, 1 PM
        (_labor(7, 5, 0), sessions.WEEKEND),  # holiday premarket
        (_labor(6, 21, 0), sessions.WEEKEND),  # Sunday 9 PM: overnight would
        # trade INTO the holiday, so it does not exist
        (_labor(7, 21, 0), sessions.OVERNIGHT),  # Monday 9 PM trades into Tue
        (_labor(8, 10, 0), sessions.REGULAR),  # Tuesday: a normal day again
    ],
)
def test_market_holidays_belong_to_the_weekend_engine(moment, expected):
    assert sessions.scheduled_session(moment, trading_days=_LABOR_WEEK) == expected


def test_unknown_calendar_falls_back_to_weekday_arithmetic():
    # _trading_days is mocked to None here: a holiday Monday then looks like
    # a regular Monday - the harmless pre-ADR-021 behaviour.
    assert sessions.scheduled_session(_labor(7, 13, 0)) == sessions.REGULAR


# Thanksgiving to New Year, 2026, as Alpaca's calendar returns it: trading
# day -> regular close. Thu 11-26 and Fri 12-25 are holidays (absent); Fri
# 11-27 and Thu 12-24 close at 1 PM.
_FULL, _HALF = dt.time(16, 0), dt.time(13, 0)
_HOLIDAY_SEASON = {
    dt.date(2026, 11, 23): _FULL,
    dt.date(2026, 11, 24): _FULL,
    dt.date(2026, 11, 25): _FULL,
    dt.date(2026, 11, 27): _HALF,
    dt.date(2026, 11, 30): _FULL,
    dt.date(2026, 12, 21): _FULL,
    dt.date(2026, 12, 22): _FULL,
    dt.date(2026, 12, 23): _FULL,
    dt.date(2026, 12, 24): _HALF,
    dt.date(2026, 12, 28): _FULL,
}


def _season(month: int, day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, month, day, hour, minute, tzinfo=ET)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        # Friday 2026-11-27, the day after Thanksgiving: a 1 PM close.
        (_season(11, 27, 9, 0), sessions.PREMARKET),
        (_season(11, 27, 12, 59), sessions.REGULAR),
        (_season(11, 27, 13, 0), sessions.AFTERHOURS),  # the close itself
        (_season(11, 27, 13, 1), sessions.AFTERHOURS),
        (_season(11, 27, 16, 0), sessions.AFTERHOURS),  # a normal close time
        (_season(11, 27, 16, 59), sessions.AFTERHOURS),
        (_season(11, 27, 17, 0), sessions.WEEKEND),  # after-hours ends at 5
        (_season(11, 27, 20, 0), sessions.WEEKEND),
        # Thursday 2026-12-24, Christmas Eve: a 1 PM close, a holiday next.
        (_season(12, 24, 12, 59), sessions.REGULAR),
        (_season(12, 24, 13, 1), sessions.AFTERHOURS),
        (_season(12, 24, 16, 0), sessions.AFTERHOURS),
        (_season(12, 24, 17, 0), sessions.WEEKEND),  # overnight would trade
        (_season(12, 24, 20, 0), sessions.WEEKEND),  # INTO Christmas Day
        (_season(12, 25, 12, 0), sessions.WEEKEND),  # Christmas itself
        # The full days either side are untouched.
        (_season(11, 25, 15, 59), sessions.REGULAR),
        (_season(11, 25, 19, 59), sessions.AFTERHOURS),
        (_season(12, 23, 16, 30), sessions.AFTERHOURS),
        (_season(12, 23, 20, 0), sessions.OVERNIGHT),  # into the half day
    ],
)
def test_early_close_days_end_the_afternoon_early(moment, expected):
    assert sessions.scheduled_session(moment, trading_days=_HOLIDAY_SEASON) == expected


def test_half_day_monday_to_thursday_evening_is_overnight():
    # A half day whose next day trades (a made-up Tuesday 1 PM close): from
    # 5 PM it is the evening that normally starts at 8 PM - overnight.
    days = {dt.date(2026, 12, 22): _HALF, dt.date(2026, 12, 23): _FULL}
    assert sessions.scheduled_session(_season(12, 22, 17, 30), trading_days=days) == sessions.OVERNIGHT


def test_calendar_rows_carry_the_close(monkeypatch):
    # The real fetch path: Alpaca's rows -> {date: close}.
    # The real _trading_days, under the autouse no-network mock, with the
    # network call itself faked.
    monkeypatch.setattr(sessions, "_trading_days", _REAL_TRADING_DAYS)
    monkeypatch.setattr(sessions, "_calendar_cache", None)
    monkeypatch.setattr(
        alpaca,
        "get_calendar",
        lambda start, end: [
            {"date": "2026-11-25", "open": "09:30", "close": "16:00"},
            {"date": "2026-11-27", "open": "09:30", "close": "13:00"},
        ],
    )
    days = sessions._trading_days()
    assert days == {dt.date(2026, 11, 25): _FULL, dt.date(2026, 11, 27): _HALF}
    assert sessions.scheduled_session(_season(11, 27, 13, 1)) == sessions.AFTERHOURS


def test_a_plain_set_of_days_still_means_full_days():
    # Callers that pass only WHICH days trade keep the 4 PM / 8 PM afternoon.
    days = frozenset({dt.date(2026, 11, 27)})
    assert sessions.scheduled_session(_season(11, 27, 13, 1), trading_days=days) == sessions.REGULAR


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
    """The formula against the *current* research_params.json.

    The parameters refresh after every recorded weekend (ADR-018), so the
    expectations derive from the same file the engine reads - the test pins
    the wiring and the arithmetic, not last week's measurements.
    """
    params = err.params()
    sizing = err.compute("NVDA", Decimal("10"), Decimal("226"))
    assert sizing["sigma"] == Decimal(params["sigma"]["NVDA"]["used"])
    assert sizing["sigma_source"] == "measured"
    assert sizing["z"] == Decimal(params["z"])
    # The measured multiplier must never silently revert to the normal
    # table's 2.326 - that regression is the whole point of ADR-018.
    assert sizing["z"] > Decimal("3")
    expected = (Decimal("10") * Decimal("226") * sizing["sigma"] * sizing["z"]).quantize(
        Decimal("0.01"), rounding=ROUND_CEILING
    )
    assert sizing["reserve"] == expected


def test_reserve_rounds_up_never_down():
    # A price chosen so sigma * z * notional lands between cents for any
    # plausible parameters: the ceiling rule must round toward more cover.
    sizing = err.compute("MCD", Decimal("1"), Decimal("100.37"))
    exact = Decimal("100.37") * sizing["sigma"] * sizing["z"]
    assert sizing["reserve"] >= exact
    assert sizing["reserve"] - exact < Decimal("0.01")


def test_unmeasured_symbol_falls_back_to_pooled_sigma():
    sizing = err.compute("ZZZZ", Decimal("1"), Decimal("100"))
    assert sizing["sigma"] == Decimal(err.params()["pooled_sigma"])
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
        self.last_trade_at = "2026-09-04T23:59:58.123456789Z"
        # The open's two Jupiter quotes: the bid prices a sell, the ask a
        # buy. Equal by default so the hand-checked cash figures stay at
        # 200; the trade-time capture tests split them.
        self.bid = Decimal("200")
        self.ask = Decimal("200")
        self.quote_error: Exception | None = None
        self.quotes: list[dict] = []

    def install(self, monkeypatch):
        # Pin the reserve parameters: the real research_params.json refreshes
        # after every recorded weekend, and the flow tests' hand-checked cash
        # figures (40.78 escrow on 2 x 200 NVDA, and so on) must not drift
        # with it. The err unit tests above cover the live file.
        monkeypatch.setattr(
            err,
            "_params_cache",
            {
                "generated_at": "pinned-for-tests",
                "z": "3.7759",
                "fees": "0.00",
                "pooled_sigma": "0.0251",
                "sigma": {"NVDA": {"used": "0.0270"}},
            },
        )
        monkeypatch.setattr(settings, "alpaca_firm_account_id", "firm-0001")
        monkeypatch.setattr(alpaca, "list_positions", lambda account_id: self.positions)
        monkeypatch.setattr(
            alpaca, "get_trading_account", lambda account_id: {"cash": self.cash}
        )
        monkeypatch.setattr(alpaca, "latest_trade", self._latest_trade)
        monkeypatch.setattr(jupiter, "SPREAD_LEG_DELAY_SECONDS", 0)
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

    def _latest_trade(self, symbol):
        if isinstance(self.last_trade_price, Exception):
            raise self.last_trade_price
        return {"p": self.last_trade_price, "t": self.last_trade_at}

    def _executable_price(self, token, side, qty, *, size_price=None):
        self.quotes.append({"side": side, "qty": qty, "size_price": size_price})
        # `size_price` marks the open's second quote (the other direction).
        if size_price is not None and self.quote_error is not None:
            raise self.quote_error
        price = self.bid if side == "sell" else self.ask
        return {
            "price": price,
            "usd_amount": price * qty,
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


# ---------------------------------------------------------------------------
# Trade-time capture: the price context at open
# ---------------------------------------------------------------------------


def _trade_row(trade_id: int):
    from models import WeekendTrade

    with db.session_scope() as session:
        row = session.get(WeekendTrade, trade_id)
        session.expunge(row)
        return row


def test_open_sell_captures_bid_ask_mid_share_and_basis(db_client, broker):
    broker.bid, broker.ask = Decimal("199"), Decimal("201")
    broker.last_trade_price = "196.50"
    trade = _open_sell(db_client)
    row = _trade_row(trade["id"])

    # The sell priced at the bid; ONE more quote, the buy, same size, sized
    # from the first quote's price (no price/v3 call).
    assert row.p_open == Decimal("199")
    assert broker.quotes == [
        {"side": "sell", "qty": Decimal("2"), "size_price": None},
        {"side": "buy", "qty": Decimal("2"), "size_price": Decimal("199")},
    ]
    assert row.open_bid == Decimal("199")
    assert row.open_ask == Decimal("201")
    assert row.open_mid == Decimal("200")
    assert row.share_ref_price == Decimal("196.50")
    assert row.share_ref_source == "alpaca_latest_trade"
    assert row.share_ref_at == dt.datetime(2026, 9, 4, 23, 59, 58, 123456, tzinfo=dt.timezone.utc)
    # 200 / 196.50 - 1, stored to Numeric(20, 10).
    assert row.open_basis == (Decimal("200") / Decimal("196.50") - 1).quantize(Decimal("1e-10"))
    # The reserve inputs, with where sigma came from and which params file.
    assert row.sigma == Decimal("0.0270")
    assert row.sigma_source == "measured"
    assert row.params_generated_at == "pinned-for-tests"
    # Money and prices come back as Decimal, never float.
    assert all(
        isinstance(value, Decimal)
        for value in (row.open_bid, row.open_ask, row.open_mid, row.share_ref_price, row.open_basis)
    )


def test_open_buy_captures_the_mirror(db_client, broker):
    broker.bid, broker.ask = Decimal("199"), Decimal("201")
    sessions.set_weekend_override(True)
    response = db_client.post("/weekend/orders", json={"symbol": "NVDA", "side": "buy", "qty": "2"})
    assert response.status_code == 200, response.text
    row = _trade_row(response.json()["id"])

    assert row.p_open == Decimal("201")  # a buy pays the ask
    assert broker.quotes[1]["side"] == "sell"
    assert row.open_bid == Decimal("199")
    assert row.open_ask == Decimal("201")
    assert row.open_mid == Decimal("200")


def test_failed_capture_never_blocks_the_trade(db_client, broker):
    broker.quote_error = jupiter.JupiterError("429 too many requests")
    broker.last_trade_price = alpaca.AlpacaError("data api down", status_code=503)
    trade = _open_sell(db_client)

    # The money flow is untouched: same escrow, same advance.
    assert trade["state"] == "provisional"
    assert trade["reserve"] == "40.78"
    assert [j["amount"] for j in broker.journals] == ["40.78", "400.00"]

    row = _trade_row(trade["id"])
    assert row.open_bid == Decimal("200")  # the sell's own quote is still known
    assert row.open_ask is None
    assert row.open_mid is None
    assert row.share_ref_price is None
    assert row.share_ref_source is None
    assert row.open_basis is None

    # The failure is on the trade's own trail, not swallowed.
    kinds = [event["kind"] for event in db_client.get(f"/weekend/orders/{trade['id']}").json()["events"]]
    assert "context_partial" in kinds


def test_capture_survives_a_missing_share_price(db_client, broker):
    broker.last_trade_price = "0"
    trade = _open_sell(db_client)
    row = _trade_row(trade["id"])
    assert row.open_mid == Decimal("200")
    assert row.share_ref_price is None
    assert row.open_basis is None


def test_fractional_weekend_orders_are_refused(db_client, broker):
    sessions.set_weekend_override(True)
    response = db_client.post(
        "/weekend/orders", json={"symbol": "NVDA", "side": "sell", "qty": "1.5"}
    )
    assert response.status_code == 422
    assert "whole_shares_only" in response.json()["detail"]


# ---------------------------------------------------------------------------
# The ledger lock (ADR-022): weekend-sold shares cannot be sold again
# ---------------------------------------------------------------------------


def test_committed_shares_cannot_be_weekend_sold_twice(db_client, broker):
    broker.positions = [{"symbol": "NVDA", "qty": "2", "qty_available": "2"}]
    _open_sell(db_client, qty="2")
    # The broker still shows 2 available - they have not moved - but the
    # engine has spoken for them.
    response = db_client.post(
        "/weekend/orders", json={"symbol": "NVDA", "side": "sell", "qty": "1"}
    )
    assert response.status_code == 400
    assert "already committed" in response.json()["detail"]


def test_regular_ticket_refuses_committed_shares(db_client, broker):
    broker.positions = [{"symbol": "NVDA", "qty": "2", "qty_available": "2"}]
    _open_sell(db_client, qty="2")
    response = db_client.post(
        "/orders", json={"symbol": "NVDA", "qty": "1", "side": "sell", "type": "market"}
    )
    assert response.status_code == 400
    assert response.json()["detail"].startswith("shares_committed")
    # Nothing reached the broker.
    assert broker.orders == []


def test_regular_ticket_allows_the_uncommitted_remainder(db_client, broker):
    broker.positions = [{"symbol": "NVDA", "qty": "3", "qty_available": "3"}]
    _open_sell(db_client, qty="2")
    response = db_client.post(
        "/orders", json={"symbol": "NVDA", "qty": "1", "side": "sell", "type": "market"}
    )
    assert response.status_code == 200, response.text
    assert len(broker.orders) == 1


def test_settled_trades_release_the_lock(db_client, broker):
    broker.positions = [{"symbol": "NVDA", "qty": "2", "qty_available": "2"}]
    trade = _open_sell(db_client, qty="2")
    db_client.post(f"/weekend/orders/{trade['id']}/settle", json={"mode": "injected", "gap": "0"})
    # Injected mode never sold the shares, so they are genuinely free again.
    response = db_client.post(
        "/orders", json={"symbol": "NVDA", "qty": "2", "side": "sell", "type": "market"}
    )
    assert response.status_code == 200, response.text


def test_reset_waits_for_open_weekend_trades(db_client, broker):
    _open_sell(db_client)
    response = db_client.post("/accounts/reset")
    assert response.status_code == 409
    assert "weekend_trades_open" in response.json()["detail"]


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
# The scheduled settlement (ADR-023)
# ---------------------------------------------------------------------------


def test_settle_all_open_settles_every_open_trade(db_client, broker, monkeypatch):
    broker.positions = [{"symbol": "NVDA", "qty": "5", "qty_available": "5"}]
    first = _open_sell(db_client, qty="2")
    second = _open_sell(db_client, qty="1")
    monkeypatch.setattr(sessions, "scheduled_session", lambda now=None, **_: sessions.REGULAR)

    with db.session_scope() as session:
        summary = weekend.settle_all_open(session)

    assert summary["settled"] == 2 and summary["failed"] == 0
    assert len(broker.orders) == 2
    for trade_id in (first["id"], second["id"]):
        assert db_client.get(f"/weekend/orders/{trade_id}").json()["state"] == "settled"


def test_settle_all_open_does_nothing_on_a_weekend(db_client, broker, monkeypatch):
    _open_sell(db_client)
    monkeypatch.setattr(sessions, "scheduled_session", lambda now=None, **_: sessions.WEEKEND)
    with db.session_scope() as session:
        summary = weekend.settle_all_open(session)
    assert summary == {"settled": 0, "breached": 0, "awaiting": 0, "failed": 0,
                       "log": ["no regulated session open; nothing settled"]}
    assert broker.orders == []


def test_settle_all_open_survives_one_refusal(db_client, broker, monkeypatch):
    broker.positions = [{"symbol": "NVDA", "qty": "5", "qty_available": "5"}]
    _open_sell(db_client, qty="1")
    _open_sell(db_client, qty="1")
    monkeypatch.setattr(sessions, "scheduled_session", lambda now=None, **_: sessions.REGULAR)

    calls = {"n": 0}
    real_create = broker._create_order

    def flaky(account_id, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise alpaca.AlpacaError("insufficient qty", status_code=403)
        return real_create(account_id, payload)

    monkeypatch.setattr(alpaca, "create_order", flaky)
    with db.session_scope() as session:
        summary = weekend.settle_all_open(session)
    assert summary["failed"] == 1 and summary["settled"] == 1
    assert any("failed" in line for line in summary["log"])


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


# ---------------------------------------------------------------------------
# v2, the locked price (ADR-033)
# ---------------------------------------------------------------------------
#
# Hand-checked figures, on the pinned parameters (z 3.7759, fees 0) and
# 2 NVDA at 200: the ERR is 400 x 0.0098 (the hedged leftover's sigma) x
# 3.7759 = 14.8015... -> ceiling 14.81. Settlement fills at 195.


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(settings, "weekend_design", "locked")


def _token_hedge(monkeypatch, chain_pnl: str, gas: str):
    """Stand in for a recorded token hedge: its close leg's P/L and gas."""
    from types import SimpleNamespace

    import hedge

    monkeypatch.setattr(hedge, "close_leg", lambda session, trade: SimpleNamespace(chain_pnl=Decimal(chain_pnl)))
    monkeypatch.setattr(hedge, "gas_usd", lambda session, trade: Decimal(gas))


def _settle_regular(client, trade, monkeypatch):
    monkeypatch.setattr(sessions, "scheduled_session", lambda now=None: sessions.REGULAR)
    return client.post(f"/weekend/orders/{trade['id']}/settle", json={"mode": "market"}).json()


def test_locked_err_is_sized_for_the_hedged_leftover(broker):
    sizing = err.compute_locked("NVDA", Decimal("2"), Decimal("200"))
    assert sizing["design"] == "locked"
    assert sizing["sigma_source"] == "hedged_leftover"
    assert sizing["reserve"] == Decimal("14.81")
    # The same trade under pass-through holds the share's whole gap: 40.78.
    assert err.compute("NVDA", Decimal("2"), Decimal("200"))["reserve"] == Decimal("40.78")


def test_locked_open_escrows_the_err_and_advances_cash(db_client, broker, locked):
    trade = _open_sell(db_client)

    assert trade["design"] == "locked"
    assert trade["reserve"] == "14.81"
    assert broker.journals[0]["amount"] == "14.81"
    assert "ERR escrow" in broker.journals[0]["description"]
    assert broker.journals[1]["amount"] == "400.00"


def test_locked_preview_shows_the_design(db_client, broker, locked):
    sessions.set_weekend_override(True)
    body = db_client.get("/weekend/preview", params={"symbol": "NVDA", "side": "sell", "qty": "2"}).json()
    assert body["design"] == "locked"
    assert body["reserve"] == "14.81"


def test_locked_hedge_loss_comes_out_of_the_err(db_client, broker, locked, monkeypatch):
    trade = _open_sell(db_client)
    broker.journals.clear()
    # Sold 2 NVDAx at 200 on the weekend, bought back at 195: +10 on chain.
    _token_hedge(monkeypatch, chain_pnl="10.00", gas="0.37")

    settled = _settle_regular(db_client, trade, monkeypatch)

    # Broker leg 2 x (195 - 200) = -10, token leg +10, gas 0.37: the
    # leftover is -0.37, so 14.81 - 0.37 = 14.44 comes back. The trader
    # kept 200 - Monday's 195 cost them nothing but the leftover.
    assert settled["state"] == "settled"
    assert settled["true_up"] == "-0.37"
    assert settled["escrow_returned"] == "14.44"
    assert broker.journals[0]["amount"] == "390.00"  # the sale, swept
    assert broker.journals[1]["amount"] == "14.44"  # the ERR, back
    kinds = [event["kind"] for event in settled["events"]]
    assert "hedge_reconciled" in kinds


def test_locked_hedge_profit_is_refunded_to_the_trader(db_client, broker, locked, monkeypatch):
    trade = _open_sell(db_client)
    # The token fell further than the share: the hedge made 12 on chain.
    _token_hedge(monkeypatch, chain_pnl="12.00", gas="0.37")

    settled = _settle_regular(db_client, trade, monkeypatch)

    # -10 + 12 - 0.37 = +1.63, refunded on top of the ERR (§6b): 16.44.
    assert settled["true_up"] == "1.63"
    assert settled["escrow_returned"] == "16.44"


def test_locked_without_a_hedge_passes_the_move_through(db_client, broker, locked, monkeypatch):
    trade = _open_sell(db_client)

    settled = _settle_regular(db_client, trade, monkeypatch)

    # hedge_mode is off in tests: no token leg, so the whole -10 move is the
    # leftover, and the event trail says so.
    assert settled["true_up"] == "-10"
    assert settled["escrow_returned"] == "4.81"
    reconciled = [e for e in settled["events"] if e["kind"] == "hedge_reconciled"]
    assert "passes through whole" in reconciled[0]["detail"]


def test_locked_leftover_beyond_the_err_breaches(db_client, broker, locked):
    trade = _open_sell(db_client)
    broker.journals.clear()

    settled = db_client.post(
        f"/weekend/orders/{trade['id']}/settle", json={"mode": "injected", "gap": "-0.2"}
    ).json()

    # Unhedged, a 20% drop is -80 against a 14.81 ERR: breached, and the
    # 65.19 beyond it is debited - the paper's shortfall cascade (§6c).
    assert settled["state"] == "breached"
    assert settled["shortfall"] == "65.19"
