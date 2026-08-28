"""ADR-016: the xStock price sampler. Jupiter and Alpaca both mocked."""

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
import sqlalchemy as sa

import alpaca
import jupiter
import sampler
from models import TokenPrice

NVDAX = "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh"
SPCXX = "Xs3oZwbHvqis4NYcf4YKWmEia2eC84wSiVrcYcTqpH8"

TOKENS = [
    {"symbol": "NVDAx", "underlying": "NVDA", "mint": NVDAX, "name": "NVIDIA xStock", "decimals": 8},
    {"symbol": "SPCXx", "underlying": None, "mint": SPCXX, "name": "SpaceX xStock", "decimals": 8},
]
QUOTES = {
    NVDAX: {
        "usdPrice": "220.23925284547732",
        "liquidity": "1623912.5859992565",
        "blockId": 442385375,
        "priceChange24h": "-3.902154455800776",
    },
    SPCXX: {"usdPrice": "101.5", "liquidity": "50000", "blockId": 442385375, "priceChange24h": None},
}
TRADES = {"NVDA": {"p": "219.955", "s": "167", "t": "2026-08-28T16:58:44.573315205Z"}}
WHEN = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)


@pytest.fixture
def feeds(monkeypatch):
    monkeypatch.setattr(jupiter, "list_xstocks", lambda: list(TOKENS))
    monkeypatch.setattr(jupiter, "prices", lambda mints: dict(QUOTES))
    monkeypatch.setattr(alpaca, "latest_trades", lambda symbols: dict(TRADES))
    monkeypatch.setattr(alpaca, "get_clock", lambda: {"is_open": True})


def test_snapshot_keeps_jupiter_digits_exactly(feeds):
    rows = {row.symbol: row for row in sampler.sample_once(WHEN)}
    nvda = rows["NVDAx"]
    assert nvda.usd_price == Decimal("220.23925284547732")  # never a float
    assert nvda.market_price == Decimal("219.955")
    assert nvda.underlying == "NVDA"
    assert nvda.block_id == 442385375
    assert nvda.market_open is True
    assert nvda.sampled_at == WHEN
    # Alpaca's nanosecond timestamp is truncated to what datetime holds.
    assert nvda.market_trade_at == datetime(2026, 8, 28, 16, 58, 44, 573315, tzinfo=timezone.utc)


def test_token_without_a_listed_share_still_records_the_token(feeds):
    rows = {row.symbol: row for row in sampler.sample_once(WHEN)}
    spacex = rows["SPCXx"]
    assert spacex.usd_price == Decimal("101.5")
    assert spacex.underlying is None
    assert spacex.market_price is None
    assert spacex.market_trade_at is None
    assert spacex.price_change_24h is None


def test_alpaca_outage_does_not_lose_the_token_observation(feeds, monkeypatch):
    def down(*args, **kwargs):
        raise alpaca.AlpacaError("boom", status_code=503)

    monkeypatch.setattr(alpaca, "latest_trades", down)
    monkeypatch.setattr(alpaca, "get_clock", down)
    rows = sampler.sample_once(WHEN)
    assert len(rows) == 2
    assert all(row.market_price is None and row.market_open is None for row in rows)


def test_token_with_no_quote_is_skipped_not_zeroed(feeds, monkeypatch):
    monkeypatch.setattr(jupiter, "prices", lambda mints: {NVDAX: QUOTES[NVDAX]})
    rows = sampler.sample_once(WHEN)
    assert [row.symbol for row in rows] == ["NVDAx"]


def test_record_appends_rows(feeds, database, session):
    assert sampler.record(sampler.sample_once(WHEN)) == 2
    stored = session.scalars(sa.select(TokenPrice).order_by(TokenPrice.symbol)).all()
    assert [row.symbol for row in stored] == ["NVDAx", "SPCXx"]
    # NUMERIC(28,10): the column keeps ten decimal places, so Jupiter's
    # fourteen are rounded at the tenth - far below a cent, and exact from
    # there on. Never a float in between.
    assert stored[0].usd_price == Decimal("220.2392528455")


# --- the Jupiter client itself --------------------------------------------


def _mock_http(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=transport, **kw))


def test_jupiter_decodes_numbers_as_strings(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["ids"] == f"{NVDAX},{SPCXX}"
        return httpx.Response(200, json={NVDAX: {"usdPrice": 220.23925284547732, "blockId": 1}})

    _mock_http(monkeypatch, handler)
    quotes = jupiter.prices([NVDAX, SPCXX, NVDAX])  # the duplicate collapses
    assert quotes[NVDAX]["usdPrice"] == "220.23925284547732"
    assert quotes[NVDAX]["blockId"] == 1


def test_jupiter_xstock_filter_and_underlying():
    assert jupiter.is_xstock({"name": "NVIDIA xStock", "symbol": "NVDAx"})
    assert not jupiter.is_xstock({"name": "Wrapped SOL", "symbol": "SOL"})
    assert jupiter.underlying_of("SPYx") == "SPY"
    # SpaceX is private; SPCX on Alpaca is an unrelated ETF.
    assert jupiter.underlying_of("SPCXx") is None


def test_jupiter_token_list_keeps_only_xstocks_sorted(monkeypatch):
    payload = [
        {"id": SPCXX, "name": "SpaceX xStock", "symbol": "SPCXx", "decimals": 8},
        {"id": "So111", "name": "Wrapped SOL", "symbol": "SOL", "decimals": 9},
        {"id": NVDAX, "name": "NVIDIA xStock", "symbol": "NVDAx", "decimals": 8},
    ]
    _mock_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    tokens = jupiter.list_xstocks()
    assert [t["symbol"] for t in tokens] == ["NVDAx", "SPCXx"]
    assert tokens[0]["underlying"] == "NVDA"
