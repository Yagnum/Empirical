"""ADR-015: the Clerk offboarding webhook and POST /accounts/reset.

The webhook tests build *real* Svix signatures with hmac/base64 against a
test secret, so the route's verification is checked against independent
maths, not against itself. Alpaca stays mocked, as everywhere in the suite:
no order, journal or closure here ever reaches the sandbox.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest
import sqlalchemy as sa

import alpaca
import offboarding
from config import settings
from models import AuditLog

DELETED_USER = "user_deleted_123"
GONE_ACCOUNT = "acct-gone-0001"
FIRM_ACCOUNT = "firm-sweep-0001"

# The secret as Clerk shows it: `whsec_` + base64 of the actual key bytes.
KEY_BYTES = b"0123456789abcdefghijklmnopqrstuv"
TEST_SECRET = "whsec_" + base64.b64encode(KEY_BYTES).decode()


def sign(body: bytes, *, msg_id: str = "msg_test_1", timestamp: int | None = None,
         key: bytes = KEY_BYTES) -> dict:
    """Real Svix headers for `body`: HMAC-SHA256 over `id.timestamp.body`."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    return {
        "svix-id": msg_id,
        "svix-timestamp": ts,
        "svix-signature": f"v1,{base64.b64encode(digest).decode()}",
    }


def user_deleted(user_id: str = DELETED_USER) -> bytes:
    return json.dumps(
        {"type": "user.deleted", "object": "event", "data": {"id": user_id, "deleted": True}}
    ).encode()


def _never(*args, **kwargs):
    raise AssertionError("this Alpaca call must not happen")


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "clerk_webhook_signing_secret", TEST_SECRET)


@pytest.fixture
def firm_account(monkeypatch):
    monkeypatch.setattr(settings, "alpaca_firm_account_id", FIRM_ACCOUNT)


def seed_audit_row(session, *, user_id: str = DELETED_USER, account_id: str = GONE_ACCOUNT):
    """The trace an onboarded user leaves behind: one audited request."""
    session.add(
        AuditLog(
            clerk_user_id=user_id,
            alpaca_account_id=account_id,
            method="POST",
            path="/funding",
            action="funding.deposit",
            outcome="ok",
            status_code=200,
            request_id="seed-request",
        )
    )
    session.commit()  # the webhook reads through its own connection


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_webhook_unconfigured_secret_is_503(client, monkeypatch):
    """Never silently accept unsigned events because a secret is missing."""
    monkeypatch.setattr(settings, "clerk_webhook_signing_secret", "")
    body = user_deleted()
    response = client.post("/webhooks/clerk", content=body, headers=sign(body))
    assert response.status_code == 503
    assert response.json()["detail"].startswith("webhook_not_configured")


def test_webhook_valid_signature_is_accepted(client, webhook_secret):
    # An event type we ignore: acceptance shows as a 204, with no Alpaca in sight.
    body = json.dumps({"type": "user.created", "data": {"id": "user_new"}}).encode()
    response = client.post("/webhooks/clerk", content=body, headers=sign(body))
    assert response.status_code == 204


def test_webhook_wrong_signature_is_401(client, webhook_secret):
    body = user_deleted()
    headers = sign(body, key=b"an-entirely-different-key-here!!")
    response = client.post("/webhooks/clerk", content=body, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_webhook_signature"}


def test_webhook_tampered_body_is_401(client, webhook_secret):
    headers = sign(user_deleted("user_victim"))
    response = client.post("/webhooks/clerk", content=user_deleted("user_attacker"), headers=headers)
    assert response.status_code == 401


def test_webhook_stale_timestamp_is_401(client, webhook_secret):
    """A correctly signed delivery replayed an hour later must not act."""
    body = user_deleted()
    headers = sign(body, timestamp=int(time.time()) - 3600)
    assert client.post("/webhooks/clerk", content=body, headers=headers).status_code == 401


def test_webhook_missing_headers_is_401(client, webhook_secret):
    assert client.post("/webhooks/clerk", content=user_deleted()).status_code == 401


def test_webhook_accepts_any_matching_v1_entry(client, webhook_secret):
    """Svix sends several space-separated signatures while rotating keys."""
    body = json.dumps({"type": "user.created", "data": {"id": "user_new"}}).encode()
    headers = sign(body)
    headers["svix-signature"] = "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= " + headers["svix-signature"]
    assert client.post("/webhooks/clerk", content=body, headers=headers).status_code == 204


# ---------------------------------------------------------------------------
# user.deleted handling
# ---------------------------------------------------------------------------


def test_webhook_other_event_types_are_204(client, webhook_secret):
    body = json.dumps({"type": "session.ended", "data": {"id": "sess_1"}}).encode()
    assert client.post("/webhooks/clerk", content=body, headers=sign(body)).status_code == 204


def test_webhook_without_a_database_is_503(client, webhook_secret):
    """No database, no user->account mapping. 503 makes Svix retry."""
    body = user_deleted()
    response = client.post("/webhooks/clerk", content=body, headers=sign(body))
    assert response.status_code == 503
    assert response.json()["detail"].startswith("offboarding_unavailable")


def test_webhook_user_who_never_had_an_account_is_204(db_client, webhook_secret):
    body = user_deleted("user_never_onboarded")
    response = db_client.post("/webhooks/clerk", content=body, headers=sign(body))
    assert response.status_code == 204


def test_webhook_liquidates_positions_and_asks_svix_to_retry(
    db_client, session, webhook_secret, monkeypatch
):
    seed_audit_row(session)
    monkeypatch.setattr(alpaca, "get_account", lambda a: {"status": "ACTIVE"})
    monkeypatch.setattr(alpaca, "list_positions", lambda a: [{"symbol": "AAPL", "qty": "4"}])
    monkeypatch.setattr(alpaca, "list_orders", lambda account_id, status, limit: [])
    submitted = []
    monkeypatch.setattr(alpaca, "close_all_positions", lambda a: submitted.append(a) or [])
    monkeypatch.setattr(alpaca, "close_account", _never)

    body = user_deleted()
    response = db_client.post("/webhooks/clerk", content=body, headers=sign(body))
    assert response.status_code == 503
    assert response.json()["detail"].startswith("liquidation_pending")
    assert submitted == [GONE_ACCOUNT]


def test_webhook_journals_cash_in_chunks_then_closes(
    db_client, session, webhook_secret, firm_account, monkeypatch
):
    """$250,000 travels as 100k + 100k + 50k (the sandbox JNLC limit)."""
    seed_audit_row(session)
    monkeypatch.setattr(alpaca, "get_account", lambda a: {"status": "ACTIVE"})
    monkeypatch.setattr(alpaca, "list_positions", lambda a: [])
    monkeypatch.setattr(alpaca, "list_orders", lambda account_id, status, limit: [])
    monkeypatch.setattr(alpaca, "get_trading_account", lambda a: {"cash": "250000"})
    journals = []
    monkeypatch.setattr(
        alpaca, "create_journal",
        lambda from_account, to_account, amount: journals.append((from_account, to_account, amount))
        or {"id": "jrnl", "status": "executed"},
    )
    closed = []
    monkeypatch.setattr(alpaca, "close_account", lambda a: closed.append(a) or {"status": "ACCOUNT_CLOSED"})

    body = user_deleted()
    response = db_client.post("/webhooks/clerk", content=body, headers=sign(body))
    assert response.status_code == 200
    assert response.json() == {
        "state": "closed",
        "alpaca_account_id": GONE_ACCOUNT,
        "returned": "250000",
    }
    assert journals == [
        (GONE_ACCOUNT, FIRM_ACCOUNT, Decimal("100000")),
        (GONE_ACCOUNT, FIRM_ACCOUNT, Decimal("100000")),
        (GONE_ACCOUNT, FIRM_ACCOUNT, Decimal("50000")),
    ]
    assert closed == [GONE_ACCOUNT]

    # The attempt is audited, keyed by the user id from the payload — which
    # is also what keeps the account findable across Svix retries.
    row = session.scalars(
        sa.select(AuditLog).where(AuditLog.action == "account.offboard")
    ).one()
    assert (row.clerk_user_id, row.alpaca_account_id, row.outcome) == (
        DELETED_USER, GONE_ACCOUNT, "ok",
    )


def test_webhook_already_closed_account_is_200(db_client, session, webhook_secret, monkeypatch):
    """A retry after the closure (or an ops closure) must not touch Alpaca again."""
    seed_audit_row(session)
    monkeypatch.setattr(alpaca, "get_account", lambda a: {"status": "ACCOUNT_CLOSED"})
    for name in ("list_positions", "list_orders", "close_all_positions",
                 "get_trading_account", "create_journal", "close_account"):
        monkeypatch.setattr(alpaca, name, _never)

    body = user_deleted()
    response = db_client.post("/webhooks/clerk", content=body, headers=sign(body))
    assert response.status_code == 200
    assert response.json() == {"state": "already_closed", "alpaca_account_id": GONE_ACCOUNT}


# ---------------------------------------------------------------------------
# POST /accounts/reset
# ---------------------------------------------------------------------------


def test_reset_when_account_not_active_is_409(client, monkeypatch):
    monkeypatch.setattr(alpaca, "get_account", lambda a: {"status": "SUBMITTED"})
    response = client.post("/accounts/reset")
    assert response.status_code == 409
    assert response.json()["detail"].startswith("account_not_active")


def test_reset_with_positions_reports_liquidating(client, monkeypatch):
    monkeypatch.setattr(alpaca, "get_account", lambda a: {"status": "ACTIVE"})
    monkeypatch.setattr(
        alpaca, "list_positions",
        lambda a: [{"symbol": "AAPL", "qty": "4"}, {"symbol": "MSFT", "qty": "1"}],
    )
    monkeypatch.setattr(alpaca, "list_orders", lambda account_id, status, limit: [{"id": "ord-1"}])
    submitted = []
    monkeypatch.setattr(alpaca, "close_all_positions", lambda a: submitted.append(a) or [])
    monkeypatch.setattr(alpaca, "create_journal", _never)

    response = client.post("/accounts/reset")
    assert response.status_code == 200
    assert response.json() == {"state": "liquidating", "positions": 2, "open_orders": 1}
    assert submitted == ["acct-test-0001"]


def test_reset_cancels_leftover_orders_then_journals(client, firm_account, monkeypatch):
    monkeypatch.setattr(alpaca, "get_account", lambda a: {"status": "ACTIVE"})
    monkeypatch.setattr(alpaca, "list_positions", lambda a: [])
    monkeypatch.setattr(
        alpaca, "list_orders",
        lambda account_id, status, limit: [{"id": "ord-1"}, {"id": "ord-2"}],
    )
    cancelled = []
    monkeypatch.setattr(alpaca, "cancel_order", lambda a, order_id: cancelled.append(order_id))
    monkeypatch.setattr(alpaca, "get_trading_account", lambda a: {"cash": "5000.50"})
    journals = []
    monkeypatch.setattr(
        alpaca, "create_journal",
        lambda from_account, to_account, amount: journals.append((from_account, to_account, amount))
        or {"id": "jrnl", "status": "executed"},
    )

    response = client.post("/accounts/reset")
    assert response.status_code == 200
    assert response.json() == {"state": "reset", "returned": "5000.50"}
    assert cancelled == ["ord-1", "ord-2"]
    assert journals == [("acct-test-0001", FIRM_ACCOUNT, Decimal("5000.50"))]


def test_reset_of_an_empty_account_is_idempotent(client, monkeypatch):
    monkeypatch.setattr(alpaca, "get_account", lambda a: {"status": "ACTIVE"})
    monkeypatch.setattr(alpaca, "list_positions", lambda a: [])
    monkeypatch.setattr(alpaca, "list_orders", lambda account_id, status, limit: [])
    monkeypatch.setattr(alpaca, "get_trading_account", lambda a: {"cash": "0"})
    monkeypatch.setattr(alpaca, "create_journal", _never)

    for _ in range(2):  # resetting twice is harmless
        response = client.post("/accounts/reset")
        assert response.status_code == 200
        assert response.json() == {"state": "reset", "returned": "0"}


def test_reset_without_a_firm_account_is_503(client, monkeypatch):
    monkeypatch.setattr(settings, "alpaca_firm_account_id", "")
    monkeypatch.setattr(alpaca, "get_account", lambda a: {"status": "ACTIVE"})
    monkeypatch.setattr(alpaca, "list_positions", lambda a: [])
    monkeypatch.setattr(alpaca, "list_orders", lambda account_id, status, limit: [])
    monkeypatch.setattr(alpaca, "get_trading_account", lambda a: {"cash": "100"})

    response = client.post("/accounts/reset")
    assert response.status_code == 503
    assert response.json()["detail"].startswith("reset_unavailable")


# ---------------------------------------------------------------------------
# The chunking maths on its own
# ---------------------------------------------------------------------------


def test_journal_chunks_cap_and_sum():
    chunks = offboarding.journal_chunks(Decimal("250000"))
    assert chunks == [Decimal("100000"), Decimal("100000"), Decimal("50000")]
    assert offboarding.journal_chunks(Decimal("100000")) == [Decimal("100000")]
    assert offboarding.journal_chunks(Decimal("100000.01")) == [
        Decimal("100000"), Decimal("0.01"),
    ]
    assert offboarding.journal_chunks(Decimal("0.01")) == [Decimal("0.01")]
    assert sum(offboarding.journal_chunks(Decimal("123456.78"))) == Decimal("123456.78")
