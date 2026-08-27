"""Account history and statements - the paper trail.

    GET /activities                    normalized activity feed, newest first
    GET /activities/export.csv         the same rows as a CSV download
    GET /documents                     Alpaca's own statements / confirms
    GET /documents/{id}/download       stream one of them back

WHY NORMALIZE: Alpaca returns two incompatible shapes from one endpoint. A
*trade* activity has `transaction_time`, `price`, `side`, `cum_qty` and no
cash amount; a *non-trade* activity (a deposit, journal, dividend or fee) has
`date`, `net_amount`, `description` and no side. A statement table wants one
shape, so this module flattens both into a single row and computes the cash
effect of a fill itself - with `Decimal`, never float (ADR-010).

Docs: https://docs.alpaca.markets/reference/getaccountactivities
      https://docs.alpaca.markets/reference/getdocsforaccount
"""

from __future__ import annotations

import csv
import io
import sys
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

import alpaca
import clerk_auth
import db
import ledger
from config import settings

router = APIRouter(tags=["activity"])

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
MAX_PAGE_SIZE = 100

# Alpaca's activity codes, grouped into the handful of categories a user
# actually distinguishes. Anything unlisted (splits, reorgs, ACATS...) is
# real but rare, and shows up as "other" rather than being dropped.
_ACTIVITY_KINDS = {
    "FILL": "fill",
    "PARTIAL_FILL": "fill",
    "CSD": "deposit",  # cash deposit (an ACH transfer landing)
    "JNLC": "journal",  # cash journal - how ADR-011 funds an account
    "JNLS": "journal",  # share journal
    "DIV": "dividend",
    "FEE": "fee",
    "INT": "fee",
}

# Statement columns, in the order they appear in the CSV. The JSON objects use
# the same keys, so the export and the on-screen table can never drift.
# `realized_pl` is the ADR-014 addition: it is filled only on a *sell* fill
# that our ledger has matched to lots, and is empty everywhere else.
COLUMNS = [
    "id", "date", "type", "symbol", "side", "qty", "price", "net_amount",
    "realized_pl", "description",
]


def _http_client() -> httpx.Client:
    """The client used to fetch a document from Alpaca's signed S3 URL.

    A named factory rather than an inline `httpx.Client(...)` so tests can
    swap in a mock transport. Patching `httpx.Client` itself is not an option:
    Starlette's TestClient *is* one, so the test would intercept its own
    request to the app.
    """
    return httpx.Client(timeout=settings.http_timeout_seconds)


def _kind(activity_type: str) -> str:
    code = activity_type.upper()
    if code in _ACTIVITY_KINDS:
        return _ACTIVITY_KINDS[code]
    # DIVNRA, DIVCGL, DIVROC... all start with DIV and all are dividend-ish.
    if code.startswith("DIV"):
        return "dividend"
    return "other"


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _day(value) -> str:
    """The YYYY-MM-DD part of either a date or an ISO timestamp."""
    text = str(value or "")
    return text[:10]


def _fill_net_amount(qty: Decimal | None, price: Decimal | None, side: str) -> str:
    """The cash effect of a fill, computed with Decimal.

    Signed from the account's point of view: buying spends cash (negative),
    selling raises it (positive). Alpaca does not send this for trade
    activities, so we derive it - and derive it exactly, because a statement
    that does not add up is worse than no statement.
    """
    if qty is None or price is None:
        return ""
    amount = (qty * price).quantize(Decimal("0.01"))
    if side.lower().startswith("buy"):
        amount = -amount
    return format(amount, "f")


def normalize(activity: dict) -> dict:
    """One Alpaca activity - either shape - as one statement row."""
    activity_type = str(activity.get("activity_type") or "")
    kind = _kind(activity_type)
    symbol = str(activity.get("symbol") or "") or None
    qty = _decimal(activity.get("qty"))

    if kind == "fill" or activity.get("transaction_time"):
        side = str(activity.get("side") or "")
        price = _decimal(activity.get("price"))
        description = " ".join(
            part for part in [side, format(qty, "f") if qty is not None else "", symbol or ""] if part
        ).strip()
        if price is not None:
            description = f"{description} @ {format(price, 'f')}"
        return {
            "id": str(activity.get("id") or ""),
            "date": _day(activity.get("transaction_time")),
            "type": kind,
            "symbol": symbol,
            "side": side or None,
            "qty": format(qty, "f") if qty is not None else None,
            "price": format(price, "f") if price is not None else None,
            "net_amount": _fill_net_amount(qty, price, side),
            # Filled in by `_attach_realized` for sells the ledger has
            # matched; null for buys and for anything not yet matched.
            "realized_pl": None,
            "description": description or activity_type,
        }

    # Non-trade activity: Alpaca already knows the cash amount.
    per_share = _decimal(activity.get("per_share_amount"))
    description = str(activity.get("description") or "").strip()
    if not description:
        # Sandbox journals arrive with an empty description; say something
        # truthful rather than showing the user a blank cell.
        description = f"{activity_type} {str(activity.get('status') or '')}".strip()
    return {
        "id": str(activity.get("id") or ""),
        "date": _day(activity.get("date") or activity.get("created_at")),
        "type": kind,
        "symbol": symbol,
        "side": None,
        "qty": format(qty, "f") if qty is not None else None,
        "price": format(per_share, "f") if per_share is not None else None,
        "net_amount": "" if activity.get("net_amount") is None else str(activity["net_amount"]),
        # A deposit or a dividend realizes nothing; the key is present on
        # every row so the frontend never has to check for its absence.
        "realized_pl": None,
        "description": description,
    }


def _attach_realized(account_id: str, rows: list[dict]) -> list[dict]:
    """Fill in `realized_pl` on the sell fills our ledger has matched.

    Best-effort by design (ADR-014): realized P/L is a number we derive on top
    of Alpaca's feed, so a database that is down or unconfigured costs the
    user a column, not their statement. Every row keeps the key with a null.
    """
    if not db.is_configured():
        return rows
    sells = [
        row["id"]
        for row in rows
        if row["type"] == "fill" and str(row.get("side") or "").lower().startswith("sell")
    ]
    if not sells:
        return rows
    try:
        with db.session_scope() as session:
            realized = ledger.realized_by_activity_id(session, account_id, sells)
    except Exception as exc:  # noqa: BLE001 - a missing column beats a 500
        print(f"[activities] realized P/L lookup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return rows
    for row in rows:
        amount = realized.get(row["id"])
        if amount is not None:
            row["realized_pl"] = ledger.money(amount)
    return rows


def _fetch(account_id: str, after: str | None, until: str | None, page_size: int) -> list[dict]:
    # Bring our own ledger up to date before reading it, so a fill that
    # settled since the last page load already has its realized P/L. This is
    # cheap on the common path: `ledger.refresh` re-asks Alpaca at most once
    # every few seconds per window, and the matcher exits on one indexed query
    # when there is nothing new. It never raises.
    ledger.refresh(account_id, after=after, until=until)
    try:
        rows = alpaca.list_activities(account_id, after=after, until=until, page_size=page_size)
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc
    return _attach_realized(account_id, [normalize(row) for row in rows])


@router.get("/activities")
def activities(
    after: str | None = Query(None, pattern=DATE_PATTERN, description="YYYY-MM-DD, inclusive"),
    until: str | None = Query(None, pattern=DATE_PATTERN, description="YYYY-MM-DD, inclusive"),
    page_size: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    account_id: str = Depends(clerk_auth.require_account_id),
) -> list[dict]:
    """Fills, deposits, journals, dividends and fees in one feed, newest first.

    Every row carries `realized_pl`. It is a decimal string only on a **sell**
    fill that our FIFO ledger has matched to opening lots, and `null`
    everywhere else - on buys, on cash movements, and on a sell whose opening
    buy is older than the history we hold.
    """
    return _fetch(account_id, after, until, page_size)


@router.get(
    "/activities/export.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "CSV attachment"}},
)
def export_activities(
    after: str | None = Query(None, pattern=DATE_PATTERN),
    until: str | None = Query(None, pattern=DATE_PATTERN),
    account_id: str = Depends(clerk_auth.require_account_id),
) -> Response:
    """The same rows as `/activities`, as a spreadsheet-ready download.

    Built in memory: a statement for a paper-trading account is at most a few
    hundred rows, so streaming would be ceremony for nothing.
    """
    rows = _fetch(account_id, after, until, MAX_PAGE_SIZE)

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: ("" if row.get(key) is None else row[key]) for key in COLUMNS})

    filename = f"yagnum-activity-{after or 'all'}-{until or date_cls.today().isoformat()}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/documents")
def documents(account_id: str = Depends(clerk_auth.require_account_id)) -> list[dict]:
    """Alpaca-generated statements, trade confirmations and tax forms.

    A brand-new sandbox account has only its account application; monthly
    statements appear after a month exists. An empty list is fine.
    """
    try:
        rows = alpaca.list_documents(account_id)
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc

    return [
        {
            "id": str(row.get("id") or ""),
            "type": str(row.get("type") or ""),
            "date": str(row.get("date") or ""),
            # Sandbox leaves `name` blank; fall back to something a human can
            # read in a download dialog.
            "name": str(row.get("name") or "") or f"{row.get('type') or 'document'} {row.get('date') or ''}".strip(),
        }
        for row in rows
    ]


@router.get(
    "/documents/{document_id}/download",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/pdf": {}}, "description": "The document bytes"}},
)
def download_document(
    document_id: str,
    account_id: str = Depends(clerk_auth.require_account_id),
) -> StreamingResponse:
    """Stream one document back to the browser.

    Alpaca answers its own download endpoint with a 301 to a presigned S3 URL
    that expires in ~15 minutes. We could hand that URL to the browser, but
    proxying is better here: the signed link never reaches client-side code,
    and the frontend does not have to special-case a cross-origin redirect it
    cannot read. Our Basic credentials are *not* sent to S3 - see
    `alpaca.document_download_url`.
    """
    try:
        signed_url = alpaca.document_download_url(account_id, document_id)
    except alpaca.AlpacaError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="document_not_found") from exc
        raise alpaca.http_error(exc) from exc

    # The extension is whatever Alpaca stored (sandbox account applications
    # are JSON; real statements are PDFs), so read it off the signed path.
    suffix = httpx.URL(signed_url).path.rsplit(".", 1)
    extension = suffix[1] if len(suffix) == 2 and len(suffix[1]) <= 5 else "pdf"
    filename = f"yagnum-document-{document_id}.{extension}"

    # Open the upstream response and check its status *before* we start our
    # own 200 — once bytes are on the wire it is too late to send an error.
    client = _http_client()
    upstream = client.send(client.build_request("GET", signed_url), stream=True)
    if upstream.status_code >= 400:
        status = upstream.status_code
        upstream.close()
        client.close()
        if status == 404:
            # Alpaca lists the document and signs a URL for it, but the sandbox
            # never wrote the file - S3 answers NoSuchKey. That is missing
            # data, not a server fault, so say so plainly.
            raise HTTPException(status_code=404, detail="document_unavailable")
        raise HTTPException(status_code=502, detail="document_fetch_failed")

    def stream():
        try:
            yield from upstream.iter_bytes()
        finally:
            upstream.close()
            client.close()

    media_type = "application/pdf" if extension == "pdf" else "application/octet-stream"
    return StreamingResponse(
        stream(),
        media_type=media_type,
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )
