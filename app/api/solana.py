"""Solana, read-only plus local signing (ADR-025).

Everything Yagnum does on-chain today goes through this module, and none of
it moves money:

    - JSON-RPC reads: does an account exist, which program owns it, what is
      the rent-exempt minimum, what does a transaction do when simulated
    - local signing of a transaction Jupiter built, with the engine wallet
    - NO sendTransaction. There is deliberately no function for it. Shadow
      mode ends at "simulated"; a live mode is a separate ADR.

THE FEE MODEL, in the words the code uses

    base fee        5,000 lamports per signature, fixed, paid to validators
    priority fee    compute units x price per unit, chosen by the sender,
                    also to validators; Jupiter proposes one when it builds
    rent            a token account (an ATA) must hold a rent-exempt
                    balance, about 0.002 SOL, once per token per wallet;
                    refundable when the account is closed
    lamport         1 / 1,000,000,000 of a SOL

The wallet that signs pays all three. Jupiter builds the transaction and
never pays for it.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from config import settings

LAMPORTS_PER_SOL = 1_000_000_000
BASE_FEE_LAMPORTS_PER_SIGNATURE = 5_000
# A classic SPL token account is 165 bytes; Token-2022 accounts with
# extensions are a little larger, so this is a floor, not the exact rent.
TOKEN_ACCOUNT_BYTES = 165

SOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"


class SolanaError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# The engine wallet
# ---------------------------------------------------------------------------


def engine_keypair() -> Keypair | None:
    """The signer, when this host holds the secret. None on hosts that only
    know the public key (the GitHub Actions jobs)."""
    secret = settings.solana_engine_keypair.strip()
    if not secret:
        return None
    try:
        return Keypair.from_base58_string(secret)
    except Exception as exc:  # solders raises a plain Exception subclass
        raise SolanaError(f"SOLANA_ENGINE_KEYPAIR is not a valid base58 keypair: {exc}") from exc


def engine_pubkey() -> str | None:
    """The wallet's address: from the keypair when present, else the
    configured public key, else None (the hedge is then disabled)."""
    keypair = engine_keypair()
    if keypair is not None:
        return str(keypair.pubkey())
    return settings.solana_engine_pubkey.strip() or None


# ---------------------------------------------------------------------------
# JSON-RPC reads
# ---------------------------------------------------------------------------


def _rpc(method: str, params: list) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.post(settings.solana_rpc_url, json=body)
    except httpx.HTTPError as exc:
        raise SolanaError(f"rpc {method}: {exc}") from exc
    if response.status_code != 200:
        raise SolanaError(f"rpc {method}: HTTP {response.status_code}")
    payload = response.json()
    if payload.get("error"):
        raise SolanaError(f"rpc {method}: {payload['error']}")
    return payload.get("result")


def account_owner(address: str) -> str | None:
    """The program that owns this account, or None when it does not exist.
    For a mint that answers "which token program is this token on?"; for an
    ATA it answers "does the wallet already have an account for it?"."""
    result = _rpc("getAccountInfo", [address, {"encoding": "base64"}])
    value = (result or {}).get("value")
    if not value:
        return None
    return str(value.get("owner"))


def rent_exempt_lamports(size: int = TOKEN_ACCOUNT_BYTES) -> int:
    return int(_rpc("getMinimumBalanceForRentExemption", [size]))


def associated_token_address(owner: str, mint: str, token_program: str) -> str:
    """The deterministic address of `owner`'s account for `mint`. Derived
    locally - a program-derived address - with no network call."""
    address, _bump = Pubkey.find_program_address(
        [
            bytes(Pubkey.from_string(owner)),
            bytes(Pubkey.from_string(token_program)),
            bytes(Pubkey.from_string(mint)),
        ],
        Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM),
    )
    return str(address)


# ---------------------------------------------------------------------------
# Transactions: decode, sign, simulate. Never send.
# ---------------------------------------------------------------------------


def decode_transaction(b64: str) -> VersionedTransaction:
    return VersionedTransaction.from_bytes(base64.b64decode(b64))


def sign(tx: VersionedTransaction, keypair: Keypair) -> VersionedTransaction:
    """Replace the placeholder signature with a real one. The message - the
    instructions and accounts - is untouched; only the signature changes."""
    return VersionedTransaction(tx.message, [keypair])


def simulate(tx: VersionedTransaction) -> dict:
    """Run the transaction against current mainnet state without sending it.

    Returns {"err": <None or the failure>, "units_consumed": int|None,
    "logs": [...]}. `sigVerify` is off so an unsigned build can be simulated
    on a host that holds no key; `replaceRecentBlockhash` keeps a slightly
    stale build simulatable.
    """
    encoded = base64.b64encode(bytes(tx)).decode()
    result = _rpc(
        "simulateTransaction",
        [
            encoded,
            {
                "encoding": "base64",
                "sigVerify": False,
                "replaceRecentBlockhash": True,
                "commitment": "processed",
            },
        ],
    )
    value = (result or {}).get("value") or {}
    return {
        "err": value.get("err"),
        "units_consumed": value.get("unitsConsumed"),
        "logs": value.get("logs") or [],
    }
