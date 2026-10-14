"""docs/RESEARCH-COLLECTION.md series A-D. Every outside call is mocked."""

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
import sqlalchemy as sa

import alpaca
import jupiter
import pyth
import sampler
import sessions
from config import settings
from models import OraclePrice, QuoteLadder, ShareTrade, TokenPrice

NVDAX = "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh"
NVDAON = "gEGtLTPNQ7jcg25zTetkbmF7teoDLcrfTnQfmn2ondo"
WHEN = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)  # a Saturday

XSTOCKS = [
    {"symbol": "NVDAx", "underlying": "NVDA", "mint": NVDAX, "name": "NVIDIA xStock", "decimals": 8, "issuer": "xstocks"},
]
QUOTES = {
    NVDAX: {
        "usdPrice": "229.6109554958841",
        "liquidity": "1623912.58",
        "blockId": 456635446,
        "scaledUiConfig": {
            "multiplier": "1.0009180758490996",
            "newMultiplier": "1.001701196801074",
            "newMultiplierEffectiveAt": "2026-09-10T00:30:00Z",
        },
    },
    NVDAON: {"usdPrice": "228.52614261493352", "liquidity": "2660.77", "blockId": 456629758},
}
# Friday's last IEX print, after hours (condition T): what a Saturday run sees.
TRADES = {"NVDA": {"p": "229.2", "s": "27", "t": "2026-10-09T20:13:50.044322289Z", "x": "V", "c": ["@", "T"]}}
TRADING_DAYS = frozenset({datetime(2026, 10, d).date() for d in (5, 6, 7, 8, 9, 12, 13)})


@pytest.fixture
def feeds(monkeypatch):
    calls = {"spread": [], "trades_feed": []}

    def spread(token, last):
        calls["spread"].append((token["symbol"], last))
        return {"bid": Decimal("229.9"), "ask": Decimal("230.1"), "bid_impact_pct": Decimal("0"),
                "ask_impact_pct": Decimal("0"), "quote_size_usd": Decimal("1000")}

    def trades(symbols, feed=None):
        calls["trades_feed"].append(feed)
        return dict(TRADES)

    monkeypatch.setattr(jupiter, "list_xstocks", lambda: list(XSTOCKS))
    monkeypatch.setattr(jupiter, "prices", lambda mints: dict(QUOTES))
    monkeypatch.setattr(jupiter, "spread_quote", spread)
    monkeypatch.setattr(alpaca, "latest_trades", trades)
    monkeypatch.setattr(alpaca, "get_clock", lambda: {"is_open": False})
    monkeypatch.setattr(sessions, "_trading_days", lambda: TRADING_DAYS)
    monkeypatch.setattr(sampler, "SPREAD_DELAY_SECONDS", 0)
    monkeypatch.setattr(sampler, "LADDER_DELAY_SECONDS", 0)
    monkeypatch.setattr(sampler, "LADDER_START_PAUSE_SECONDS", 0)
    monkeypatch.setattr(jupiter, "SPREAD_LEG_DELAY_SECONDS", 0)
    monkeypatch.setattr(settings, "pyth_api_key", "")
    return calls


# --- A. Ondo beside xStocks ----------------------------------------------


def test_ondo_list_is_the_verified_fixed_set():
    tokens = jupiter.list_ondo()
    assert {t["symbol"] for t in tokens} == {
        "SPYon", "QQQon", "NVDAon", "TSLAon", "GOOGLon", "CRCLon", "AAPLon", "METAon",
    }
    for token in tokens:
        assert token["issuer"] == "ondo"
        assert token["decimals"] == 9
        assert token["mint"].endswith("ondo")  # Ondo's vanity suffix
        assert token["symbol"] == token["underlying"] + "on"
    assert len({t["mint"] for t in tokens}) == len(tokens)


def test_ondo_and_xstock_twins_share_an_underlying_without_colliding(feeds):
    rows = {row.symbol: row for row in sampler.sample_once(WHEN)}
    assert rows["NVDAx"].underlying == rows["NVDAon"].underlying == "NVDA"
    assert rows["NVDAx"].issuer == "xstocks"
    assert rows["NVDAon"].issuer == "ondo"
    assert rows["NVDAon"].mint == NVDAON
    # Both rows carry the same share print: the comparison is like for like.
    assert rows["NVDAx"].market_price == rows["NVDAon"].market_price == Decimal("229.2")
    # Ondo tokens Jupiter returned no price for are skipped, not zeroed.
    assert "SPYon" not in rows


def test_multiplier_is_recorded_and_sizes_the_spread_in_raw_tokens(feeds):
    rows = {row.symbol: row for row in sampler.sample_once(WHEN)}
    assert rows["NVDAx"].ui_multiplier == Decimal("1.001701196801074")
    assert rows["NVDAon"].ui_multiplier is None  # none reported
    spread_last = dict(feeds["spread"])
    assert spread_last["NVDAx"] == Decimal("229.6109554958841") * Decimal("1.001701196801074")
    assert spread_last["NVDAon"] == Decimal("228.52614261493352")


def test_ui_multiplier_switches_at_its_effective_moment():
    entry = {"scaledUiConfig": {"multiplier": "1.0", "newMultiplier": "1.02",
                                "newMultiplierEffectiveAt": "2026-10-10T00:00:00Z"}}
    assert jupiter.ui_multiplier(entry, datetime(2026, 10, 9, tzinfo=timezone.utc)) == Decimal("1.0")
    assert jupiter.ui_multiplier(entry, datetime(2026, 10, 10, tzinfo=timezone.utc)) == Decimal("1.02")
    assert jupiter.ui_multiplier({"usdPrice": "1"}) is None
    assert jupiter.ui_multiplier({"scaledUiConfig": {"multiplier": "0"}}) is None


# --- B. The depth ladder --------------------------------------------------


def test_ladder_quote_prices_per_share_both_ways(monkeypatch):
    token = {"symbol": "NVDAx", "mint": NVDAX, "decimals": 8}
    seen = []

    def quote(input_mint, output_mint, amount):
        seen.append((input_mint, output_mint, amount))
        if input_mint == jupiter.USDC_MINT:
            # $10,000 buys 43.47826087 raw tokens.
            return {"outAmount": "4347826087", "priceImpactPct": "0.0012",
                    "routePlan": [{"swapInfo": {"label": "Whirlpool"}}, {"swapInfo": {"label": "GoonFi V2"}}]}
        return {"outAmount": "9980000000", "priceImpactPct": "0.002", "routePlan": []}

    monkeypatch.setattr(jupiter, "swap_quote", quote)
    multiplier = Decimal("1.0017")
    buy = jupiter.ladder_quote(token, "buy", Decimal("10000"), Decimal("229.61"), multiplier)
    assert seen[0] == (jupiter.USDC_MINT, NVDAX, 10_000_000_000)
    assert buy["share_amount"] == Decimal("43.47826087") * multiplier
    assert buy["price_usd"] == Decimal("10000.000000") / (Decimal("43.47826087") * multiplier)
    assert buy["route"] == "Whirlpool>GoonFi V2"
    assert buy["in_amount"] == Decimal(10_000_000_000)

    sell = jupiter.ladder_quote(token, "sell", Decimal("10000"), Decimal("229.61"), multiplier)
    raw_qty = (Decimal("10000") / (Decimal("229.61") * multiplier)).quantize(Decimal("1e-8"))
    assert seen[1][0] == NVDAX and seen[1][2] == int(raw_qty * 10**8)
    assert sell["usd_amount"] == Decimal("9980")
    assert sell["price_usd"] == Decimal("9980") / (raw_qty * multiplier)
    assert all(not isinstance(v, float) for v in sell.values())


def _ladder_snap(sampled_at=WHEN):
    tokens = list(XSTOCKS) + [t for t in jupiter.list_ondo() if t["symbol"] == "NVDAon"]
    return sampler.Snapshot(sampled_at, tokens=tokens, quotes=dict(QUOTES))


def test_ladder_covers_each_size_and_side_and_records_no_route(feeds, monkeypatch):
    monkeypatch.setattr(settings, "ladder_symbols", "NVDAx,NVDAon,SPYx")
    monkeypatch.setattr(settings, "ladder_sizes_usd", "10000,50000")

    def rung(token, side, size, price, multiplier):
        if token["symbol"] == "NVDAon" and size == Decimal("50000"):
            raise jupiter.JupiterError('{"error":"Could not find any route"}', status_code=400)
        return {"in_amount": Decimal(1), "out_amount": Decimal(2), "share_amount": Decimal("1"),
                "usd_amount": size, "price_usd": size, "price_impact_pct": Decimal("0"), "route": "X"}

    monkeypatch.setattr(jupiter, "ladder_quote", rung)
    rows = sampler.ladder_rows(_ladder_snap())
    # SPYx is not in this snapshot: skipped. 2 tokens x 2 sizes x 2 sides.
    assert len(rows) == 8
    statuses = {(r.symbol, r.size_usd, r.side): r.status for r in rows}
    assert statuses[("NVDAon", Decimal("50000"), "buy")] == "no_route"
    assert statuses[("NVDAx", Decimal("50000"), "sell")] == "ok"
    assert {r.issuer for r in rows} == {"xstocks", "ondo"}
    assert all(r.sampled_at == WHEN for r in rows)


def test_ladder_stops_at_the_first_429(feeds, monkeypatch):
    monkeypatch.setattr(settings, "ladder_symbols", "NVDAx,NVDAon")
    calls = []

    def rung(token, side, size, price, multiplier):
        calls.append((token["symbol"], side, size))
        if len(calls) == 2:
            raise jupiter.JupiterError("Too Many Requests", status_code=429)
        return {"price_usd": Decimal("1")}

    monkeypatch.setattr(jupiter, "ladder_quote", rung)
    rows = sampler.ladder_rows(_ladder_snap())
    assert len(calls) == 2  # no third call after the 429
    assert [r.status for r in rows] == ["ok", "rate_limited"]


def test_ladder_gate_is_off_without_a_database():
    assert sampler.ladder_due(WHEN) is False


# --- C. The oracle record -------------------------------------------------


def _mock_http(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=transport, **kw))


NVDA_FEED = "b1073854ed24cbc755dc527418f52b7d271f6cc967bbf8d8129112b18860a593"


def test_pyth_without_a_key_is_skipped_not_failed(feeds):
    with pytest.raises(pyth.PythUnavailable):
        pyth.latest([NVDA_FEED])
    snap = sampler.sample_all(WHEN, ladder=False)
    assert snap.oracles == []
    assert len(snap.prices) == 2


def test_pyth_rows_keep_exact_digits_and_the_frozen_publish_time(feeds, monkeypatch):
    monkeypatch.setattr(settings, "pyth_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path.endswith("/v2/updates/price/latest")
        assert NVDA_FEED in request.url.params.get_list("ids[]")
        return httpx.Response(200, json={"parsed": [{
            "id": NVDA_FEED,
            "price": {"price": "21101503", "conf": "11050", "expo": -5, "publish_time": 1791576000},
        }]})

    _mock_http(monkeypatch, handler)
    rows = sampler.oracle_rows(WHEN)
    assert len(rows) == 1  # feeds Pyth did not return are absent, not zero
    row = rows[0]
    assert (row.symbol, row.feed_kind, row.feed_symbol) == ("NVDA", "regular", "Equity.US.NVDA/USD")
    assert row.price == Decimal("21101503") and row.expo == -5
    assert row.price_usd == Decimal("211.01503")
    assert row.conf_usd == Decimal("0.11050")
    assert row.publish_time == datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)  # Friday close


def test_pyth_http_failure_does_not_sink_the_run(feeds, monkeypatch):
    monkeypatch.setattr(settings, "pyth_api_key", "test-key")
    _mock_http(monkeypatch, lambda request: httpx.Response(401, text="unauthorized"))
    snap = sampler.sample_all(WHEN, ladder=False)
    assert snap.oracles == []
    assert len(snap.prices) == 2
    assert len(snap.share_trades) == 1


def test_pyth_feed_table_is_well_formed():
    assert len({feed["id"] for feed in pyth.FEEDS}) == len(pyth.FEEDS)
    for feed in pyth.FEEDS:
        assert len(feed["id"]) == 64 and int(feed["id"], 16) >= 0
        assert feed["kind"] in {"regular", "index_24_7"}
        assert feed["feed_symbol"].endswith(f".{feed['symbol']}/USD")


# --- D. Share prints ------------------------------------------------------


def test_share_trades_record_feed_conditions_and_session(feeds):
    snap = sampler.sample_all(WHEN, ladder=False)
    assert feeds["trades_feed"] == ["iex"]  # the feed is pinned, not guessed
    (trade,) = snap.share_trades
    assert trade.symbol == "NVDA"
    assert trade.feed == "iex"
    assert trade.price == Decimal("229.2")
    assert trade.size == Decimal("27")
    assert trade.exchange == "V"
    assert trade.conditions == "@,T"
    assert trade.session == "afterhours"  # 16:13 ET Friday
    assert trade.trade_at == datetime(2026, 10, 9, 20, 13, 50, 44322, tzinfo=timezone.utc)


def test_alpaca_latest_trades_sends_the_feed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["feed"] == "iex"
        assert request.url.params["symbols"] == "NVDA,SPY"
        return httpx.Response(200, json={"trades": {"NVDA": {"p": 229.2, "t": "2026-10-09T20:13:50Z"}}})

    _mock_http(monkeypatch, handler)
    trades = alpaca.latest_trades(["NVDA", "SPY"], feed="iex")
    assert trades["NVDA"]["p"] == "229.2"  # text, never a float


# --- The whole run ----------------------------------------------------------


def test_every_extra_series_failing_still_keeps_the_token_rows(feeds, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(sampler, "share_trade_rows", boom)
    monkeypatch.setattr(sampler, "oracle_rows", boom)
    monkeypatch.setattr(sampler, "ladder_rows", boom)
    snap = sampler.sample_all(WHEN, ladder=True)
    assert len(snap.prices) == 2
    assert snap.share_trades == snap.oracles == snap.ladder == []


def test_record_all_writes_every_series(feeds, monkeypatch, database, session):
    monkeypatch.setattr(settings, "pyth_api_key", "test-key")
    _mock_http(monkeypatch, lambda request: httpx.Response(200, json={"parsed": [{
        "id": NVDA_FEED, "price": {"price": "21101503", "conf": "11050", "expo": -5, "publish_time": 1791576000},
    }]}))
    monkeypatch.setattr(settings, "ladder_symbols", "NVDAx")
    monkeypatch.setattr(settings, "ladder_sizes_usd", "10000")
    monkeypatch.setattr(jupiter, "ladder_quote", lambda *a: {
        "in_amount": Decimal("10000000000"), "out_amount": Decimal("4347826087"),
        "share_amount": Decimal("43.5521"), "usd_amount": Decimal("10000"),
        "price_usd": Decimal("229.6100"), "price_impact_pct": Decimal("0.0012"), "route": "Whirlpool"})

    assert sampler.ladder_due(WHEN) is True  # empty table
    snap = sampler.sample_all(WHEN, ladder=None)
    written = sampler.record_all(snap)
    assert written == {"token_prices": 2, "share_trades": 1, "oracle_prices": 1, "quote_ladder": 2}
    assert sampler.ladder_due(WHEN) is False  # a rung younger than 55 minutes

    issuers = dict(session.execute(sa.select(TokenPrice.symbol, TokenPrice.issuer)).all())
    assert issuers == {"NVDAx": "xstocks", "NVDAon": "ondo"}
    assert session.scalar(sa.select(OraclePrice.price_usd)) == Decimal("211.01503")
    assert session.scalar(sa.select(ShareTrade.session)) == "afterhours"
    assert session.scalar(sa.select(sa.func.count()).select_from(QuoteLadder)) == 2
