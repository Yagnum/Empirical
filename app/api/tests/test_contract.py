"""Contract tests: the exact JSON the frontend is being built against.

These run the real FastAPI routers, the real Pydantic validation and the real
serialisation. Only the outermost hop - `alpaca.*`, the functions that make
HTTP calls - is replaced, with fixtures copied verbatim from live sandbox
responses on 2026-08-26. So a change that breaks the frontend breaks a test
here, without needing the network or the market to be open.

The fixtures are deliberately *ugly* where Alpaca is ugly: `"limit_price":
"1"` and not `"1.00"`, equity as `"10000.000000"`, an empty journal
description. Pretty fixtures hide real bugs.
"""

from __future__ import annotations

import httpx
import pytest

import alpaca
import routes_activity

# --- fixtures copied from live sandbox responses ---------------------------

CLOCK = {
    "is_open": False,
    "next_close": "2026-08-27T16:00:00-04:00",
    "next_open": "2026-08-27T09:30:00-04:00",
    "timestamp": "2026-08-26T16:09:31.278659289-04:00",
}

ASSETS = [
    {"symbol": "AAPL", "name": "Apple Inc. Common Stock", "exchange": "NASDAQ",
     "tradable": True, "fractionable": True},
    {"symbol": "AAPU", "name": "Direxion Daily AAPL Bull 2X ETF", "exchange": "NASDAQ",
     "tradable": True, "fractionable": True},
    {"symbol": "ZZZ", "name": "Zebra Apple Holdings", "exchange": "NYSE",
     "tradable": False, "fractionable": False},
    {"symbol": "MSFT", "name": "Microsoft Corp", "exchange": "NASDAQ",
     "tradable": True, "fractionable": True},
    {"symbol": "MLP", "name": "Maui Land & Pineapple Co.", "exchange": "NYSE",
     "tradable": True, "fractionable": True},
]

QUOTE = {"ap": "0", "as": 0, "ax": " ", "bp": "294.37", "bs": 40,
         "t": "2026-08-26T20:00:02.918926467Z", "z": "C"}
TRADE = {"p": "313.475", "s": 70, "t": "2026-08-26T19:59:58.234937572Z"}

BARS = [
    {"t": "2026-08-25T04:00:00Z", "o": "310.79", "h": "313.59", "l": "308.21",
     "c": "309.9", "v": 26081057, "n": 605411, "vw": "309.85971"},
    {"t": "2026-08-26T04:00:00Z", "o": "310.3", "h": "315.43", "l": "308.8001",
     "c": "313.45", "v": 34067005, "n": 650035, "vw": "313.224391"},
]

ORDER = {
    "id": "72e4e6a7-4197-476f-88f5-0dfd4076b13d",
    "client_order_id": "c85a0d0d-81a6-4d4e-9af2-b2aceac47740",
    "created_at": "2026-08-26T20:18:18.608642739Z",
    "submitted_at": "2026-08-26T20:18:18.608642739Z",
    "filled_at": None,
    "canceled_at": None,
    "symbol": "AAPL",
    "asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
    "asset_class": "us_equity",
    "qty": "1",
    "filled_qty": "0",
    "limit_price": "1",
    "stop_price": None,
    "filled_avg_price": None,
    "type": "limit",
    "order_type": "limit",
    "side": "buy",
    "time_in_force": "day",
    "status": "accepted",
}

POSITION = {
    "asset_class": "us_equity", "asset_id": "93f5", "avg_entry_price": "172.08",
    "change_today": "0.0189483657034581", "cost_basis": "688.32", "current_price": "172.08",
    "exchange": "NASDAQ", "lastday_price": "168.88", "market_value": "688.32",
    "qty": "4", "qty_available": "4", "side": "long", "symbol": "AAPL",
    "unrealized_intraday_pl": "0", "unrealized_pl": "0", "unrealized_plpc": "0",
}

HISTORY = {
    "timestamp": [1787356800, 1787616000, 1787702400],
    "equity": ["0.000000", "10000.000000", "10000.000000"],
    "profit_loss": ["0.000000", "0.000000", "0.000000"],
    "profit_loss_pct": ["0.000000", "0.000000", "0.000000"],
    "base_value": "10000.000000",
    "base_value_asof": "2026-08-24",
    "timeframe": "1D",
}

JOURNAL_ACTIVITY = {
    "id": "20260824000000000::89c772bb-9d9c-4c7b-8ad9-66362bfab759",
    "account_id": "acct-test-0001", "activity_type": "JNLC", "date": "2026-08-24",
    "created_at": "2026-08-25T02:30:30.631376Z", "net_amount": "10000",
    "description": "", "status": "executed", "currency": "USD",
}

FILL_ACTIVITY = {
    "id": "20260826000000000::aaaa1111", "account_id": "acct-test-0001",
    "activity_type": "FILL", "transaction_time": "2026-08-26T13:31:02.123456Z",
    "type": "fill", "price": "313.45", "qty": "2", "side": "buy", "symbol": "AAPL",
    "leaves_qty": "0", "order_id": "72e4e6a7", "cum_qty": "2", "order_status": "filled",
}

DOCUMENT = {"id": "0732f24d-87f7-483a-81e5-f3e76e8fdc7e", "name": "",
            "type": "account_application", "sub_type": "", "date": "2026-08-24"}


def _error(status: int, message: str) -> alpaca.AlpacaError:
    return alpaca.AlpacaError(message, status_code=status)


def _raiser(status: int, message: str):
    def fail(*args, **kwargs):
        raise _error(status, message)

    return fail


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_health_is_public(anon_client):
    assert anon_client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/market/clock"),
        ("GET", "/market/assets?q=AAPL"),
        ("GET", "/market/quotes/AAPL"),
        ("GET", "/market/bars/AAPL"),
        ("GET", "/orders"),
        ("POST", "/orders"),
        ("GET", "/positions"),
        ("GET", "/portfolio/history"),
        ("GET", "/activities"),
        ("GET", "/activities/export.csv"),
        ("GET", "/documents"),
    ],
)
def test_every_route_requires_a_token(anon_client, method, path):
    response = anon_client.request(method, path)
    assert response.status_code == 401
    assert response.json()["detail"].startswith("missing_authorization_header")


def test_openapi_advertises_bearer_auth():
    """This is what puts the Authorize lock button on /docs."""
    from main import app

    schema = app.openapi()
    scheme = schema["components"]["securitySchemes"]["ClerkSessionToken"]
    assert scheme == {
        "type": "http",
        "scheme": "bearer",
        "description": scheme["description"],
    }
    assert schema["paths"]["/orders"]["post"]["security"] == [{"ClerkSessionToken": []}]


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------


def test_clock(client, monkeypatch):
    monkeypatch.setattr(alpaca, "get_clock", lambda: CLOCK)
    assert client.get("/market/clock").json() == {
        "is_open": False,
        "next_open": "2026-08-27T09:30:00-04:00",
        "next_close": "2026-08-27T16:00:00-04:00",
        "timestamp": "2026-08-26T16:09:31.278659289-04:00",
    }


def test_asset_search_ranks_symbol_before_name(client, monkeypatch):
    monkeypatch.setattr(alpaca, "active_equity_assets", lambda **_: ASSETS)
    body = client.get("/market/assets?q=aapl&limit=10").json()
    assert [row["symbol"] for row in body] == ["AAPL", "AAPU"]
    assert body[0] == {
        "symbol": "AAPL",
        "name": "Apple Inc. Common Stock",
        "exchange": "NASDAQ",
        "tradable": True,
        "fractionable": True,
    }

    # A name-only hit still matches, but ranks below every symbol hit - and a
    # word-boundary name match beats one buried mid-word. Regression guard:
    # live, "apple" used to return Maui Land & PINEAPPLE above Apple Inc.
    apple = client.get("/market/assets?q=apple").json()
    assert [row["symbol"] for row in apple] == ["AAPL", "ZZZ", "MLP"]


def test_asset_search_empty_query_returns_nothing(client, monkeypatch):
    monkeypatch.setattr(alpaca, "active_equity_assets", lambda **_: ASSETS)
    assert client.get("/market/assets?q=  ").json() == []


def test_quote_merges_quote_and_trade(client, monkeypatch):
    monkeypatch.setattr(alpaca, "latest_quote", lambda symbol: QUOTE)
    monkeypatch.setattr(alpaca, "latest_trade", lambda symbol: TRADE)
    assert client.get("/market/quotes/aapl").json() == {
        "symbol": "AAPL",
        "bid": "294.37",
        "ask": "0",
        "bid_size": 40,
        "ask_size": 0,
        "last": "313.475",
        "last_size": 70,
        "timestamp": "2026-08-26T20:00:02.918926467Z",
    }


def test_quote_unknown_symbol_is_404(client, monkeypatch):
    monkeypatch.setattr(alpaca, "latest_quote", _raiser(404, "no quote found for ZZZZQQ"))
    response = client.get("/market/quotes/ZZZZQQ")
    assert response.status_code == 404
    assert response.json() == {"detail": "unknown_symbol"}


def test_bars_shape(client, monkeypatch):
    monkeypatch.setattr(alpaca, "bars", lambda symbol, timeframe, limit: BARS)
    body = client.get("/market/bars/AAPL?timeframe=1Day&limit=2").json()
    assert body == [
        {"t": "2026-08-25T04:00:00Z", "o": "310.79", "h": "313.59", "l": "308.21",
         "c": "309.9", "v": 26081057},
        {"t": "2026-08-26T04:00:00Z", "o": "310.3", "h": "315.43", "l": "308.8001",
         "c": "313.45", "v": 34067005},
    ]
    # Oldest first, and volume is the one numeric field.
    assert body[0]["t"] < body[1]["t"]
    assert isinstance(body[0]["v"], int)
    assert all(isinstance(bar[key], str) for bar in body for key in "ohlc")


def test_bars_rejects_unknown_timeframe(client):
    response = client.get("/market/bars/AAPL?timeframe=2Day")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("invalid_timeframe")


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def test_place_limit_order(client, monkeypatch):
    sent = {}

    def fake_create(account_id, payload):
        sent["account_id"] = account_id
        sent["payload"] = payload
        return ORDER

    monkeypatch.setattr(alpaca, "create_order", fake_create)
    response = client.post(
        "/orders",
        json={"symbol": "aapl", "qty": "1", "side": "buy", "type": "limit",
              "limit_price": "1.00", "time_in_force": "day"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": "72e4e6a7-4197-476f-88f5-0dfd4076b13d",
        "client_order_id": "c85a0d0d-81a6-4d4e-9af2-b2aceac47740",
        "symbol": "AAPL",
        "qty": "1",
        "filled_qty": "0",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "status": "accepted",
        "limit_price": "1",
        "filled_avg_price": None,
        "submitted_at": "2026-08-26T20:18:18.608642739Z",
        "filled_at": None,
        "canceled_at": None,
    }
    # The symbol is upper-cased and money leaves as a string, not a number.
    assert sent["payload"] == {
        "symbol": "AAPL", "qty": "1", "side": "buy", "type": "limit",
        "time_in_force": "day", "limit_price": "1.00",
    }
    assert sent["account_id"] == "acct-test-0001"


def test_market_order_defaults_to_day(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(alpaca, "create_order", lambda a, p: sent.update(p) or ORDER)
    client.post("/orders", json={"symbol": "AAPL", "qty": 2, "side": "sell", "type": "market"})
    assert sent["time_in_force"] == "day"
    assert sent["qty"] == "2"
    assert "limit_price" not in sent


@pytest.mark.parametrize(
    "body",
    [
        {"symbol": "AAPL", "qty": "1", "side": "buy", "type": "limit"},          # no price
        {"symbol": "AAPL", "qty": "0", "side": "buy", "type": "market"},         # qty 0
        {"symbol": "AAPL", "qty": "-1", "side": "buy", "type": "market"},        # qty negative
        {"symbol": "AAPL", "qty": "1", "side": "hold", "type": "market"},        # bad side
        {"symbol": "AAPL", "qty": "1", "side": "buy", "type": "stop"},           # bad type
        {"symbol": "AAPL", "qty": "1", "side": "buy", "type": "market",
         "time_in_force": "ioc"},                                                # bad TIF
        {"qty": "1", "side": "buy", "type": "market"},                           # no symbol
    ],
)
def test_invalid_order_bodies_are_422(client, body):
    assert client.post("/orders", json=body).status_code == 422


def test_broker_rejection_is_400_with_alpacas_message(client, monkeypatch):
    """Insufficient buying power arrives as a 403 from Alpaca; the user did
    nothing malformed, so it must not look like an auth problem or a 422."""
    monkeypatch.setattr(alpaca, "create_order", _raiser(403, "insufficient buying power"))
    response = client.post(
        "/orders", json={"symbol": "AAPL", "qty": "99999", "side": "buy", "type": "market"}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "alpaca_rejected: insufficient buying power"}


def test_unknown_asset_rejection_is_also_400(client, monkeypatch):
    monkeypatch.setattr(alpaca, "create_order", _raiser(422, 'asset "ZZZZQQ" not found'))
    response = client.post(
        "/orders", json={"symbol": "ZZZZQQ", "qty": "1", "side": "buy", "type": "market"}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": 'alpaca_rejected: asset "ZZZZQQ" not found'}


def test_list_orders_passes_filters_through(client, monkeypatch):
    seen = {}

    def fake_list(account_id, status, limit):
        seen.update(status=status, limit=limit)
        return [ORDER]

    monkeypatch.setattr(alpaca, "list_orders", fake_list)
    body = client.get("/orders?status=all&limit=25").json()
    assert seen == {"status": "all", "limit": 25}
    assert len(body) == 1 and body[0]["id"] == ORDER["id"]


def test_list_orders_rejects_bad_status(client):
    assert client.get("/orders?status=nonsense").status_code == 422


def test_get_order_not_found(client, monkeypatch):
    monkeypatch.setattr(alpaca, "get_order", _raiser(404, "order not found"))
    response = client.get("/orders/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "order_not_found"}


def test_cancel_reports_the_status_alpaca_settles_on(client, monkeypatch):
    monkeypatch.setattr(alpaca, "cancel_order", lambda a, o: None)
    monkeypatch.setattr(alpaca, "get_order", lambda a, o: {**ORDER, "status": "pending_cancel"})
    response = client.delete(f"/orders/{ORDER['id']}")
    assert response.status_code == 200
    assert response.json() == {"id": ORDER["id"], "status": "pending_cancel"}


def test_cancel_of_a_filled_order_is_409(client, monkeypatch):
    monkeypatch.setattr(alpaca, "cancel_order", _raiser(422, "order is not cancelable"))
    response = client.delete(f"/orders/{ORDER['id']}")
    assert response.status_code == 409
    assert response.json() == {"detail": "order_not_cancelable"}


def test_cancel_of_an_unknown_order_is_404(client, monkeypatch):
    monkeypatch.setattr(alpaca, "cancel_order", _raiser(404, "order not found"))
    response = client.delete("/orders/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "order_not_found"}


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


def test_positions(client, monkeypatch):
    monkeypatch.setattr(alpaca, "list_positions", lambda a: [POSITION])
    assert client.get("/positions").json() == [
        {
            "symbol": "AAPL",
            "qty": "4",
            "side": "long",
            "avg_entry_price": "172.08",
            "current_price": "172.08",
            "market_value": "688.32",
            "cost_basis": "688.32",
            "unrealized_pl": "0",
            "unrealized_plpc": "0",
            "change_today": "0.0189483657034581",
        }
    ]


def test_empty_positions_is_an_empty_list(client, monkeypatch):
    monkeypatch.setattr(alpaca, "list_positions", lambda a: [])
    assert client.get("/positions").json() == []


def test_portfolio_history(client, monkeypatch):
    seen = {}

    def fake_history(account_id, period, timeframe):
        seen.update(period=period, timeframe=timeframe)
        return HISTORY

    monkeypatch.setattr(alpaca, "portfolio_history", fake_history)
    body = client.get("/portfolio/history?period=1M&timeframe=1D").json()
    assert seen == {"period": "1M", "timeframe": "1D"}
    assert body == {
        "timestamps": [1787356800, 1787616000, 1787702400],
        "equity": ["0.000000", "10000.000000", "10000.000000"],
        "profit_loss": ["0.000000", "0.000000", "0.000000"],
        "profit_loss_pct": ["0.000000", "0.000000", "0.000000"],
        "base_value": "10000.000000",
    }
    assert all(isinstance(value, int) for value in body["timestamps"])
    assert all(isinstance(value, str) for value in body["equity"])


def test_portfolio_history_gaps_become_empty_strings(client, monkeypatch):
    """An intraday series has nulls where the market was shut. The arrays must
    stay the same length as `timestamps` so the chart can draw a gap."""
    monkeypatch.setattr(
        alpaca, "portfolio_history",
        lambda a, p, t: {**HISTORY, "equity": ["10000.00", None, "10000.00"]},
    )
    assert client.get("/portfolio/history").json()["equity"] == ["10000.00", "", "10000.00"]


def test_portfolio_history_rejects_bad_period(client):
    assert client.get("/portfolio/history?period=7Y").status_code == 422
    assert client.get("/portfolio/history?timeframe=2H").status_code == 422


# ---------------------------------------------------------------------------
# Activities, statements and documents
# ---------------------------------------------------------------------------


def test_activities_normalizes_both_alpaca_shapes(client, monkeypatch):
    monkeypatch.setattr(
        alpaca, "list_activities",
        lambda a, after=None, until=None, page_size=100: [FILL_ACTIVITY, JOURNAL_ACTIVITY],
    )
    body = client.get("/activities").json()
    assert body[0] == {
        "id": "20260826000000000::aaaa1111",
        "date": "2026-08-26",
        "type": "fill",
        "symbol": "AAPL",
        "side": "buy",
        "qty": "2",
        "price": "313.45",
        # 2 x 313.45, negative because buying spends cash. Decimal, not float.
        "net_amount": "-626.90",
        "description": "buy 2 AAPL @ 313.45",
    }
    assert body[1] == {
        "id": "20260824000000000::89c772bb-9d9c-4c7b-8ad9-66362bfab759",
        "date": "2026-08-24",
        "type": "journal",
        "symbol": None,
        "side": None,
        "qty": None,
        "price": None,
        "net_amount": "10000",
        # Sandbox sends an empty description; we say something truthful.
        "description": "JNLC executed",
    }


@pytest.mark.parametrize(
    "activity_type,expected",
    [("FILL", "fill"), ("PARTIAL_FILL", "fill"), ("CSD", "deposit"), ("JNLC", "journal"),
     ("JNLS", "journal"), ("DIV", "dividend"), ("DIVNRA", "dividend"), ("FEE", "fee"),
     ("INT", "fee"), ("SPLIT", "other"), ("ACATC", "other")],
)
def test_activity_type_mapping(activity_type, expected):
    row = routes_activity.normalize({"id": "x", "activity_type": activity_type, "date": "2026-08-26"})
    assert row["type"] == expected


def test_activities_date_filters_reach_alpaca(client, monkeypatch):
    seen = {}

    def fake(account_id, after=None, until=None, page_size=100):
        seen.update(after=after, until=until, page_size=page_size)
        return []

    monkeypatch.setattr(alpaca, "list_activities", fake)
    client.get("/activities?after=2026-08-01&until=2026-08-26&page_size=50")
    assert seen == {"after": "2026-08-01", "until": "2026-08-26", "page_size": 50}


def test_activities_rejects_a_malformed_date(client):
    assert client.get("/activities?after=01-08-2026").status_code == 422


def test_csv_export(client, monkeypatch):
    monkeypatch.setattr(
        alpaca, "list_activities",
        lambda a, after=None, until=None, page_size=100: [FILL_ACTIVITY, JOURNAL_ACTIVITY],
    )
    response = client.get("/activities/export.csv?after=2026-08-01&until=2026-08-26")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        'attachment; filename="yagnum-activity-2026-08-01-2026-08-26.csv"'
    )
    lines = response.text.strip().splitlines()
    assert lines[0] == "id,date,type,symbol,side,qty,price,net_amount,description"
    assert lines[1] == (
        "20260826000000000::aaaa1111,2026-08-26,fill,AAPL,buy,2,313.45,-626.90,buy 2 AAPL @ 313.45"
    )
    # Nulls become empty cells, not the string "None".
    assert lines[2].startswith("20260824000000000::89c772bb-9d9c-4c7b-8ad9-66362bfab759,"
                              "2026-08-24,journal,,,,,10000,")


def test_documents(client, monkeypatch):
    monkeypatch.setattr(alpaca, "list_documents", lambda a: [DOCUMENT])
    assert client.get("/documents").json() == [
        {
            "id": "0732f24d-87f7-483a-81e5-f3e76e8fdc7e",
            "type": "account_application",
            "date": "2026-08-24",
            "name": "account_application 2026-08-24",
        }
    ]


def test_documents_empty_is_fine(client, monkeypatch):
    monkeypatch.setattr(alpaca, "list_documents", lambda a: [])
    assert client.get("/documents").json() == []


def test_document_download_streams_the_bytes(client, monkeypatch):
    monkeypatch.setattr(
        alpaca, "document_download_url",
        lambda account_id, document_id: "https://s3.example.test/doc.pdf?sig=abc",
    )
    # A mock transport, not a patched httpx.Client: the TestClient is itself
    # an httpx.Client, so patching the class would hijack the test's own call.
    fetched = {}

    def handler(request: httpx.Request) -> httpx.Response:
        fetched["url"] = str(request.url)
        return httpx.Response(200, content=b"%PDF-1.4 fake")

    monkeypatch.setattr(
        routes_activity, "_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = client.get("/documents/doc-1/download")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 fake"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="yagnum-document-doc-1.pdf"'
    )
    # Our Alpaca credentials must never travel to S3.
    assert fetched["url"] == "https://s3.example.test/doc.pdf?sig=abc"


def test_document_that_alpaca_never_wrote_is_404(client, monkeypatch):
    """Sandbox lists an account application, signs a URL for it, and S3 then
    answers NoSuchKey. Verified live - it must read as missing, not broken."""
    monkeypatch.setattr(
        alpaca, "document_download_url",
        lambda account_id, document_id: "https://s3.example.test/doc.json?sig=abc",
    )
    monkeypatch.setattr(
        routes_activity, "_http_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404, text="NoSuchKey"))
        ),
    )
    response = client.get("/documents/doc-1/download")
    assert response.status_code == 404
    assert response.json() == {"detail": "document_unavailable"}


def test_document_download_not_found(client, monkeypatch):
    monkeypatch.setattr(alpaca, "document_download_url", _raiser(404, "document not found"))
    response = client.get("/documents/nope/download")
    assert response.status_code == 404
    assert response.json() == {"detail": "document_not_found"}


# ---------------------------------------------------------------------------
# The existing Phase 1 contract must not move
# ---------------------------------------------------------------------------


def test_phase_one_routes_are_unchanged(client, monkeypatch):
    monkeypatch.setattr(
        alpaca, "get_trading_account",
        lambda account_id: {"status": "ACTIVE", "currency": "USD", "cash": "10000",
                            "buying_power": "10000", "portfolio_value": "10000",
                            "equity": "10000"},
    )
    monkeypatch.setattr("clerk_auth.get_user", lambda user_id: object())
    monkeypatch.setattr("clerk_auth.get_alpaca_account_id", lambda user: "acct-test-0001")
    assert client.get("/accounts/me").json() == {
        "alpaca_account_id": "acct-test-0001",
        "status": "ACTIVE",
        "currency": "USD",
        "cash": "10000",
        "buying_power": "10000",
        "portfolio_value": "10000",
        "equity": "10000",
    }


def test_bars_helper_asks_far_enough_back():
    """A regression guard for the bug that cost the most time: without an
    explicit `start`, Alpaca defaults to today and returns a single bar."""
    from datetime import date, datetime, timezone

    start = date.fromisoformat(alpaca._bars_start("1Day", 200))
    span = (datetime.now(timezone.utc).date() - start).days
    assert span >= 200 * 7 / 5  # at least 200 trading days of calendar time
