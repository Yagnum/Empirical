# Exploring the Yagnum API in Postman

Postman lets you send requests to the API by hand and read the replies —
useful for understanding what the frontend receives before any UI exists.

Two files live here:

| File | What it is |
| --- | --- |
| `yagnum.postman_collection.json` | Every route, grouped into folders, with example bodies |
| `yagnum.postman_environment.json` | The variables the collection uses: `base_url`, `token`, `symbol`, `order_id`, `document_id` |

Both are **generated** from the running API's `/openapi.json` by
`app/api/scripts/make_postman.py`. Do not hand-edit them; change the API (or
that script's example values) and regenerate.

## Five steps

1. **Start the API.**

   ```
   cd app/api
   uv run uvicorn main:app --reload
   ```

   Check it is alive at <http://localhost:8000/health>.

2. **Mint a session token.** Every route except `/health` needs one.

   ```
   cd app/api
   uv run python scripts/dev_token.py
   ```

   It prints one long line — that is the token. It is valid for **one hour**;
   run the command again when requests start coming back `401`.

3. **Import both files.** In Postman: **Import** → drag in
   `yagnum.postman_collection.json` and `yagnum.postman_environment.json`.

4. **Paste the token into the environment.** Pick **Yagnum Local** from the
   environment dropdown (top right), open it, and paste the token into the
   `token` variable's *current value*. Save.

5. **Send a request.** Start with `GET /health` (no token needed), then
   `GET /accounts/me`. Bearer auth is set once at the collection level, so
   every other request picks up `{{token}}` automatically.

## Things worth knowing

- **The order to walk the folders in** is the order they are numbered.
  `POST /accounts` creates the brokerage account, `POST /funding` puts
  sandbox cash in it, and only then will `POST /orders` succeed.
- **`{{order_id}}` and `{{document_id}}` start empty.** Send `POST /orders` or
  `GET /documents` first, copy an `id` from the response into the environment,
  then the `GET`/`DELETE` requests for that id will work.
- **The example order is a limit buy of 1 AAPL at $1.00.** It is far below the
  market, so it will not fill — safe to create and cancel at any hour. Send
  `DELETE /orders/{{order_id}}` when you are done with it.
- **Money and prices are strings**, not numbers (`"313.45"`). That is
  deliberate — see ADR-010 in `docs/DECISIONS.md`.
- **Fills only happen while the market is open.** `GET /market/clock` tells
  you whether it is, and when it next opens.

## The Jupiter trade flow (a second, hand-written collection)

`jupiter-flow.postman_collection.json` is different: it is not generated,
and it does not exercise Yagnum's routes. It walks the whole life of a token
trade on Jupiter, one request per step, in order:

| Step | Request | What you learn |
| --- | --- | --- |
| 1 | Token search | The mint address is the token's identity; the symbol is not |
| 2 | Price | The last swap price — for watching, never for trading |
| 3 | Quote, sell direction | The bid: base units in, USDC out, the effective price |
| 4 | Quote, buy direction | The ask, and the spread between 3 and 4 |
| 5 | Swap build | The unsigned transaction — the step Yagnum never signs |
| 6 | Solana: latest swaps on the pool | The public ledger, including failed swaps |
| 7 | Solana: one transaction in full | Balances before and after; decimals carried with every amount |
| 8 | Yagnum `GET /market/token/NVDA` | How the app wraps step 1 and 2 (needs the API and a token) |

To use it:

1. Import the file. It carries its own variables; no environment file is
   needed. Steps 1–7 need no token and no server.
2. Open the Postman console (**View → Show Postman Console**). Each step's
   Tests tab decodes the reply into plain language there — base units to
   tokens, the effective price, the spread, the on-chain outcome.
3. Send the requests in order. Step 1 saves the mint for the rest; step 3
   saves the quote that step 5 needs; step 6 saves a signature for step 7.
4. Read `docs/JUPITER-FLOW.md` alongside. Its sections match the steps.

Nothing in this collection moves money. The wallet address in step 5 is a
placeholder public key, and no private key exists anywhere in the project.

## Regenerating

With the API running:

```
cd app/api
uv run python scripts/make_postman.py
```

Or without a server: `uv run python scripts/make_postman.py --offline`.

## The same thing without Postman

FastAPI serves interactive docs at <http://localhost:8000/docs>. Click
**Authorize**, paste the same token, and every endpoint gets a working
"Try it out" button.
