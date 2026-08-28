"""ADR-016/017: the historical backfill. GeckoTerminal and Alpaca both mocked."""

from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest
import sqlalchemy as sa

import alpaca
import backfill
import geckoterminal
from models import MarketBar, TokenCandle

NVDAX = "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh"
POOL = "49iMatQtoyabsYAQc8GafVq6aeBFVDxSRH44oiatyyw6"
NOW = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)

POOLS_BODY = {
    "data": [
        {"id": "solana_shallowUSDC", "attributes": {"name": "NVDAx / USDC", "reserve_in_usd": "12000.5"}},
        {"id": f"solana_{POOL}", "attributes": {"name": "NVDAx / USDC", "reserve_in_usd": "1950000.25"}},
        {"id": "solana_deepSOL", "attributes": {"name": "NVDAx / SOL", "reserve_in_usd": "9000000"}},
    ]
}
HISTORY_LIMIT_BODY = {
    "errors": [{"status": "401", "title": "You can only access data from the past 180 days"}]
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(geckoterminal, "_sleep", lambda seconds: None)


def _mock_http(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=transport, **kw))


def _ohlcv_body(rows):
    return {"data": {"attributes": {"ohlcv_list": rows}}}


# --- GeckoTerminal client ---------------------------------------------------


def test_pool_selection_prefers_usdc_by_reserve(monkeypatch):
    _mock_http(monkeypatch, lambda request: httpx.Response(200, json=POOLS_BODY))
    chosen = geckoterminal.deepest_usdc_pool(NVDAX)
    # The SOL pool is deeper, but USDC is the quote we price in.
    assert chosen["address"] == POOL
    assert chosen["reserve_usd"] == "1950000.25"


def test_pool_selection_falls_back_to_deepest_of_any_kind():
    only_sol = [
        {"address": "a", "name": "NVDAx / SOL", "reserve_usd": "10"},
        {"address": "b", "name": "NVDAx / WETH", "reserve_usd": "500"},
    ]
    assert geckoterminal.choose_pool(only_sol)["address"] == "b"
    assert geckoterminal.choose_pool([]) is None


def test_ohlcv_decodes_numbers_as_strings_and_maps_to_utc(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/pools/{POOL}/ohlcv/hour")
        assert request.url.params["limit"] == "1000"
        assert request.headers["accept"] == "application/json"
        return httpx.Response(200, json=_ohlcv_body([[1756400400, 220.23925284547732, 221.1, 219.9, 220.5, 12345.678]]))

    _mock_http(monkeypatch, handler)
    page = geckoterminal.ohlcv(POOL, "hour")
    assert page[0][1] == "220.23925284547732"  # never a float
    rows = backfill.candle_rows("NVDAx", NVDAX, POOL, "hour", page)
    assert rows[0]["bucket_start"] == datetime(2025, 8, 28, 17, 0, tzinfo=timezone.utc)
    assert rows[0]["open"] == Decimal("220.23925284547732")
    assert rows[0]["volume_usd"] == Decimal("12345.678")
    assert rows[0]["pool"] == POOL


def test_history_limit_401_is_a_distinct_exception(monkeypatch):
    _mock_http(monkeypatch, lambda request: httpx.Response(401, json=HISTORY_LIMIT_BODY))
    with pytest.raises(geckoterminal.HistoryLimitReached) as caught:
        geckoterminal.ohlcv(POOL, "hour", before_timestamp=1000)
    assert caught.value.status_code == 401
    assert isinstance(caught.value, geckoterminal.GeckoTerminalError)


def test_other_errors_stay_generic(monkeypatch):
    _mock_http(monkeypatch, lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(geckoterminal.GeckoTerminalError) as caught:
        geckoterminal.ohlcv(POOL, "hour")
    assert not isinstance(caught.value, geckoterminal.HistoryLimitReached)
    assert caught.value.status_code == 500


def test_rate_limit_is_retried_once(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json=_ohlcv_body([]))

    _mock_http(monkeypatch, handler)
    assert geckoterminal.ohlcv(POOL, "day") == []
    assert len(calls) == 2


# --- the pager -------------------------------------------------------------


def test_pager_uses_oldest_ts_and_stops_at_the_wall(monkeypatch):
    hour = 3600
    newest = int(NOW.timestamp())
    page1 = [[newest - i * hour, 1, 1, 1, 1, 0] for i in range(geckoterminal.PAGE_LIMIT)]
    page2_top = newest - geckoterminal.PAGE_LIMIT * hour
    page2 = [[page2_top - i * hour, 1, 1, 1, 1, 0] for i in range(geckoterminal.PAGE_LIMIT)]
    befores = []

    def handler(request: httpx.Request) -> httpx.Response:
        befores.append(request.url.params.get("before_timestamp"))
        if len(befores) == 1:
            return httpx.Response(200, json=_ohlcv_body(page1))
        if len(befores) == 2:
            return httpx.Response(200, json=_ohlcv_body(page2))
        return httpx.Response(401, json=HISTORY_LIMIT_BODY)

    _mock_http(monkeypatch, handler)
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = backfill.fetch_candles(POOL, "hour", cutoff)
    assert befores == [None, str(page1[-1][0]), str(page2[-1][0])]
    assert len(rows) == 2 * geckoterminal.PAGE_LIMIT


def test_pager_stops_at_the_cutoff_and_drops_older_candles(monkeypatch):
    hour = 3600
    newest = int(NOW.timestamp())
    page = [[newest - i * hour, 1, 1, 1, 1, 0] for i in range(geckoterminal.PAGE_LIMIT)]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_ohlcv_body(page))

    _mock_http(monkeypatch, handler)
    cutoff = datetime(2026, 8, 27, 17, 0, tzinfo=timezone.utc)  # one day back
    rows = backfill.fetch_candles(POOL, "hour", cutoff)
    assert len(calls) == 1
    assert len(rows) == 25  # 24 hours back, inclusive


# --- Monday windows --------------------------------------------------------


def test_monday_window_is_dst_aware():
    # March 2, 2026: still EST (UTC-5). DST begins March 8.
    start, end = backfill.monday_window_utc(date(2026, 3, 2))
    assert start == datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 2, 15, 30, tzinfo=timezone.utc)
    # July 6, 2026: EDT (UTC-4).
    start, end = backfill.monday_window_utc(date(2026, 7, 6))
    assert start == datetime(2026, 7, 6, 8, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 6, 14, 30, tzinfo=timezone.utc)


def test_mondays_since_lists_only_mondays_in_range():
    mondays = backfill.mondays_since(NOW, days=180)
    assert all(day.weekday() == 0 for day in mondays)
    assert mondays[-1] == date(2026, 8, 24)
    assert mondays[0] == date(2026, 3, 2)  # 2026-03-01 is a Sunday; rolled forward
    assert len(mondays) == 26
    # Judged in ET: 01:00 UTC Tuesday is still Monday evening in New York.
    late = datetime(2026, 8, 25, 1, 0, tzinfo=timezone.utc)
    assert backfill.mondays_since(late, days=7)[-1] == date(2026, 8, 24)


# --- Alpaca bar mapping ----------------------------------------------------


DAILY_BARS = {
    "bars": [
        {"t": "2026-08-27T04:00:00Z", "o": 218.5, "h": 221.0, "l": 217.25, "c": 219.955, "v": 1234567, "n": 4321, "vw": 219.4321},
        {"t": "2026-08-28T04:00:00Z", "o": 220.0, "h": 222.0, "l": 219.0, "c": 220.24, "v": 987654, "n": 3210, "vw": 220.1},
    ],
    "next_page_token": None,
}


def test_daily_bars_map_t_to_bucket_start_and_keep_vw_n(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=DAILY_BARS)

    _mock_http(monkeypatch, handler)
    bars = backfill.fetch_bars("NVDA", {"timeframe": "1Day", "start": "2024-08-01", "feed": "iex"})
    rows = backfill.bar_rows("NVDA", "1Day", bars)
    assert seen[0]["start"] == "2024-08-01"
    assert rows[0]["bucket_start"] == datetime(2026, 8, 27, 4, 0, tzinfo=timezone.utc)
    assert rows[0]["close"] == Decimal("219.955")
    assert rows[0]["vwap"] == Decimal("219.4321")
    assert rows[0]["trade_count"] == 4321
    assert rows[0]["volume"] == Decimal("1234567")


def test_bars_follow_next_page_token(monkeypatch):
    tokens_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        tokens_seen.append(request.url.params.get("page_token"))
        if len(tokens_seen) == 1:
            return httpx.Response(200, json={"bars": DAILY_BARS["bars"][:1], "next_page_token": "abc"})
        return httpx.Response(200, json={"bars": DAILY_BARS["bars"][1:], "next_page_token": None})

    _mock_http(monkeypatch, handler)
    bars = backfill.fetch_bars("NVDA", {"timeframe": "1Day"})
    assert tokens_seen == [None, "abc"]
    assert len(bars) == 2


def test_minute_backfill_asks_for_the_utc_window(monkeypatch, database):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"bars": [], "next_page_token": None})

    _mock_http(monkeypatch, handler)
    assert backfill.backfill_market_minutes("NVDA", date(2026, 3, 2)) == 0
    assert seen[0]["start"] == "2026-03-02T09:00:00Z"
    assert seen[0]["end"] == "2026-03-02T15:30:00Z"
    assert seen[0]["timeframe"] == "1Min"
    assert seen[0]["feed"] == "iex"


# --- upserts (real Postgres) ---------------------------------------------


def test_candle_upsert_is_idempotent(database, session):
    page = [[1756400400, 220.23925284547732, 221.1, 219.9, 220.5, 12345.678], [1756396800, 219, 220, 218, 219.5, 100]]
    rows = backfill.candle_rows("NVDAx", NVDAX, POOL, "hour", geckoterminal_decoded(page))
    assert backfill.upsert_candles(rows) == 2
    assert backfill.upsert_candles(rows) == 0
    stored = session.scalars(sa.select(TokenCandle).order_by(TokenCandle.bucket_start)).all()
    assert len(stored) == 2
    assert stored[1].open == Decimal("220.2392528455")  # NUMERIC(28,10)
    assert stored[1].source == "geckoterminal"


def test_bar_upsert_is_idempotent(database, session):
    rows = backfill.bar_rows("NVDA", "1Day", DAILY_BARS["bars"])
    assert backfill.upsert_bars(rows) == 2
    assert backfill.upsert_bars(rows) == 0
    assert session.scalar(sa.select(sa.func.count()).select_from(MarketBar)) == 2


def test_backfill_token_end_to_end(monkeypatch, database, session):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pools"):
            return httpx.Response(200, json=POOLS_BODY)
        if request.url.params.get("before_timestamp"):
            return httpx.Response(401, json=HISTORY_LIMIT_BODY)
        return httpx.Response(200, json=_ohlcv_body([[int(NOW.timestamp()) - 3600, 1, 2, 0.5, 1.5, 10]]))

    _mock_http(monkeypatch, handler)
    assert backfill.backfill_token("NVDAx", NVDAX, "hour", now=NOW) == 1
    assert backfill.backfill_token("NVDAx", NVDAX, "hour", now=NOW) == 0
    stored = session.scalars(sa.select(TokenCandle)).one()
    assert stored.pool == POOL and stored.symbol == "NVDAx"


def geckoterminal_decoded(page):
    """What the client would hand back: numbers as strings."""
    return [[row[0], *[str(value) for value in row[1:]]] for row in page]


def test_alpaca_error_propagates(monkeypatch):
    def down(path, params=None):
        raise alpaca.AlpacaError("nope", status_code=403)

    monkeypatch.setattr(alpaca, "_data_request", down)
    with pytest.raises(alpaca.AlpacaError):
        backfill.fetch_bars("NVDA", {"timeframe": "1Day"})
