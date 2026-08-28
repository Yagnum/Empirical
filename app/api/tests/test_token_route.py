"""GET /market/token/{symbol}: the xStock beside its share. Jupiter and Alpaca mocked."""

from decimal import Decimal

import alpaca
import jupiter
import routes_market

NVDAX = "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh"
TOKEN = {"symbol": "NVDAx", "underlying": "NVDA", "mint": NVDAX, "name": "NVIDIA xStock", "decimals": 8}
QUOTE = {"usdPrice": "218.733158103151", "liquidity": "1623912.58", "blockId": 442385375, "priceChange24h": "-3.9"}


def _feeds(monkeypatch, *, trade=None, clock=None):
    monkeypatch.setattr(jupiter, "cached_xstocks", lambda force_refresh=False: [TOKEN])
    monkeypatch.setattr(jupiter, "prices", lambda mints: {NVDAX: QUOTE})
    monkeypatch.setattr(alpaca, "latest_trades", lambda symbols: {"NVDA": trade} if trade else {})
    monkeypatch.setattr(alpaca, "get_clock", lambda: clock or {"is_open": True})


def test_token_route_prices_the_twin_and_signs_the_gap(client, monkeypatch):
    _feeds(monkeypatch, trade={"p": "218.42", "t": "2026-08-28T17:08:33.123456789Z"})
    body = client.get("/market/token/nvda").json()
    assert body["symbol"] == "NVDA" and body["token"] == "NVDAx" and body["mint"] == NVDAX
    assert body["usd_price"] == "218.733158103151"  # Jupiter's digits, untouched
    assert body["market_price"] == "218.42"
    assert body["market_trade_at"] == "2026-08-28T17:08:33.123456Z"
    assert body["market_open"] is True
    # (218.733158103151 / 218.42 - 1) * 100 = +0.14337..., three places, signed.
    assert body["gap_pct"] == "+0.143"
    assert body["liquidity_usd"] == "1623912.58"
    assert body["block_id"] == 442385375


def test_gap_percent_is_decimal_and_signed():
    assert routes_market.gap_percent(Decimal("99"), Decimal("100")) == "-1.000"
    assert routes_market.gap_percent(Decimal("100"), Decimal("100")) == "+0.000"
    assert routes_market.gap_percent(Decimal("100"), None) is None
    assert routes_market.gap_percent(Decimal("100"), Decimal("0")) is None


def test_symbol_without_a_token_is_404(client, monkeypatch):
    _feeds(monkeypatch)
    response = client.get("/market/token/KO")
    assert response.status_code == 404
    assert response.json()["detail"] == "no_token"


def test_alpaca_outage_leaves_market_fields_null(client, monkeypatch):
    _feeds(monkeypatch)

    def down(*args, **kwargs):
        raise alpaca.AlpacaError("boom", status_code=503)

    monkeypatch.setattr(alpaca, "latest_trades", down)
    monkeypatch.setattr(alpaca, "get_clock", down)
    body = client.get("/market/token/NVDA").json()
    assert body["usd_price"] == "218.733158103151"
    assert body["market_price"] is None and body["market_open"] is None and body["gap_pct"] is None


def test_jupiter_outage_is_502(client, monkeypatch):
    def down(*args, **kwargs):
        raise jupiter.JupiterError("timed out")

    monkeypatch.setattr(jupiter, "cached_xstocks", down)
    response = client.get("/market/token/NVDA")
    assert response.status_code == 502
    assert response.json()["detail"].startswith("jupiter_unreachable")
