"""Regenerate the Postman collection from the API's own OpenAPI schema.

WHY GENERATE IT
    A hand-written Postman collection rots the moment a route changes.
    FastAPI already publishes the truth at /openapi.json, so the collection is
    derived from it: every route, every query parameter and every path
    parameter comes from the schema. Only the *examples* are hand-written
    (see EXAMPLE_BODIES / EXAMPLE_VALUES below), because a schema knows the
    shape of a request but not a sensible value to put in it.

USAGE (from app/api)
    uv run uvicorn main:app --port 8000        # in another terminal
    uv run python scripts/make_postman.py

    # or, without a server running:
    uv run python scripts/make_postman.py --offline

    Writes docs/postman/yagnum.postman_collection.json and
           docs/postman/yagnum.postman_environment.json

After regenerating, skim the folder names and examples - the generator is
deliberately dumb about wording.

Postman collection format v2.1:
https://schema.postman.com/json/collection/v2.1.0/collection.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "docs" / "postman"
DEFAULT_SCHEMA_URL = "http://localhost:8000/openapi.json"

COLLECTION_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

# Fixed ids, so regenerating updates the collection you already imported
# instead of leaving a second copy beside it.
COLLECTION_ID = "6c1f0a2e-9d4b-4f7a-9c31-5a0b2e7d1f01"
ENVIRONMENT_ID = "6c1f0a2e-9d4b-4f7a-9c31-5a0b2e7d1f02"

# Tag -> the folder it becomes, in the order a newcomer should read them.
FOLDERS = [
    ("health", "0 - Health"),
    ("accounts", "1 - Account"),
    ("funding", "2 - Funding"),
    ("market", "3 - Market data"),
    ("orders", "4 - Orders"),
    ("portfolio", "5 - Portfolio"),
    ("activity", "6 - Activity & statements"),
    ("pnl", "7 - Realized P/L"),
]

# Request bodies. The schema says "an OrderRequest goes here"; only a human
# knows that a $1.00 limit on AAPL is the one order you can safely place while
# the market is closed.
EXAMPLE_BODIES = {
    ("post", "/accounts"): None,
    ("post", "/funding"): {"amount": "10000"},
    ("post", "/orders"): {
        "symbol": "AAPL",
        "qty": "1",
        "side": "buy",
        "type": "limit",
        "limit_price": "1.00",
        "time_in_force": "day",
    },
}

# Values for query and path parameters, by parameter name.
EXAMPLE_VALUES = {
    "symbol": "{{symbol}}",
    "order_id": "{{order_id}}",
    "document_id": "{{document_id}}",
    "q": "AAPL",
    "limit": "10",
    "timeframe": "1Day",
    "status": "open",
    "period": "1M",
    "page_size": "100",
    "after": "2026-08-01",
    "until": "2026-08-31",
    # Any stable string works; a UUID is what a real client would send.
    "Idempotency-Key": "11111111-2222-3333-4444-555555555555",
}

# Route-specific overrides where the generic value above is wrong.
ROUTE_VALUES = {
    ("get", "/orders"): {"limit": "50"},
    ("get", "/market/bars/{symbol}"): {"limit": "200"},
    ("get", "/portfolio/history"): {"timeframe": "1D"},
}

ENVIRONMENT_VALUES = [
    ("base_url", "http://localhost:8000", "default"),
    # Left empty on purpose: paste the output of scripts/dev_token.py here.
    # "secret" keeps it out of the file when the environment is exported.
    ("token", "", "secret"),
    ("symbol", "AAPL", "default"),
    ("order_id", "", "default"),
    ("document_id", "", "default"),
]


def load_schema(url: str, offline: bool) -> dict:
    if offline:
        from main import app

        return app.openapi()
    try:
        return httpx.get(url, timeout=15).raise_for_status().json()
    except httpx.HTTPError as exc:
        raise SystemExit(
            f"Could not read {url} ({type(exc).__name__}). "
            "Start the API first, or pass --offline."
        ) from exc


def build_url(path: str, operation: dict, method: str) -> dict:
    """A Postman URL object: raw string plus the parsed pieces it needs."""
    overrides = ROUTE_VALUES.get((method, path), {})

    def value_for(name: str) -> str:
        return overrides.get(name, EXAMPLE_VALUES.get(name, ""))

    segments = []
    for segment in path.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            segments.append(value_for(segment[1:-1]))
        else:
            segments.append(segment)

    query = []
    for parameter in operation.get("parameters", []):
        if parameter.get("in") != "query":
            continue
        name = parameter["name"]
        query.append(
            {
                "key": name,
                "value": value_for(name),
                "description": parameter.get("description") or "",
                # Optional parameters ship disabled so the request works as-is
                # and the reader can see what else is available.
                "disabled": not parameter.get("required", False) and name in ("after", "until"),
            }
        )

    raw = "{{base_url}}/" + "/".join(segments)
    if query:
        enabled = [item for item in query if not item["disabled"]]
        if enabled:
            raw += "?" + "&".join(f"{item['key']}={item['value']}" for item in enabled)

    url: dict = {"raw": raw, "host": ["{{base_url}}"], "path": segments}
    if query:
        url["query"] = query
    return url


def build_request(path: str, method: str, operation: dict) -> dict:
    request: dict = {
        "method": method.upper(),
        "header": [],
        "url": build_url(path, operation, method),
        "description": (operation.get("description") or operation.get("summary") or "").strip(),
    }

    # Header parameters the schema declares (today: Idempotency-Key on
    # POST /orders). Shipped disabled, so the request works untouched and the
    # reader can still see the header exists and tick it on.
    for parameter in operation.get("parameters", []):
        if parameter.get("in") != "header":
            continue
        request["header"].append(
            {
                "key": parameter["name"],
                "value": EXAMPLE_VALUES.get(parameter["name"], ""),
                "description": parameter.get("description") or "",
                "disabled": not parameter.get("required", False),
            }
        )

    body = EXAMPLE_BODIES.get((method, path))
    if body is not None:
        request["header"].append({"key": "Content-Type", "value": "application/json"})
        request["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, indent=2),
            "options": {"raw": {"language": "json"}},
        }

    if path == "/health":
        # The only public route: prove it needs no token.
        request["auth"] = {"type": "noauth"}
    return request


def build_collection(schema: dict) -> dict:
    folders = {tag: {"name": name, "item": []} for tag, name in FOLDERS}
    extra: dict[str, dict] = {}

    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            tag = (operation.get("tags") or ["other"])[0]
            folder = folders.get(tag) or extra.setdefault(tag, {"name": tag, "item": []})
            folder["item"].append(
                {
                    "name": f"{method.upper()} {path}",
                    "request": build_request(path, method, operation),
                    "response": [],
                }
            )

    ordered = [folders[tag] for tag, _ in FOLDERS if folders[tag]["item"]]
    ordered.extend(extra.values())
    for folder in ordered:
        folder["item"].sort(key=lambda item: item["name"])

    return {
        "info": {
            "_postman_id": COLLECTION_ID,
            "name": schema.get("info", {}).get("title", "Yagnum API"),
            "description": (
                "Every Yagnum API route, generated from /openapi.json by "
                "app/api/scripts/make_postman.py.\n\n"
                "Set `token` in the environment to a session token from "
                "`uv run python scripts/dev_token.py`. Bearer auth is set once "
                "here at the collection level, so every request inherits it.\n\n"
                "Money and prices are strings (ADR-010)."
            ),
            "schema": COLLECTION_SCHEMA,
        },
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]},
        "item": ordered,
        "variable": [{"key": "base_url", "value": "http://localhost:8000", "type": "string"}],
    }


def build_environment() -> dict:
    return {
        "id": ENVIRONMENT_ID,
        "name": "Yagnum Local",
        "values": [
            {"key": key, "value": value, "type": kind, "enabled": True}
            for key, value, kind in ENVIRONMENT_VALUES
        ],
        "_postman_variable_scope": "environment",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_SCHEMA_URL, help="where to read /openapi.json")
    parser.add_argument("--offline", action="store_true", help="import the app instead of calling it")
    args = parser.parse_args()

    schema = load_schema(args.url, args.offline)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    collection_path = OUTPUT_DIR / "yagnum.postman_collection.json"
    environment_path = OUTPUT_DIR / "yagnum.postman_environment.json"
    collection_path.write_text(json.dumps(build_collection(schema), indent=2) + "\n", encoding="utf-8")
    environment_path.write_text(json.dumps(build_environment(), indent=2) + "\n", encoding="utf-8")

    total = sum(len(folder["item"]) for folder in json.loads(collection_path.read_text(encoding="utf-8"))["item"])
    print(f"{collection_path}  ({total} requests)")
    print(environment_path)


if __name__ == "__main__":
    main()
