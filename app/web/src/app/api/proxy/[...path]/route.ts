import type { NextRequest } from "next/server";

import { forward } from "@/lib/api";

/*
  The read-only window the browser gets onto the API.

  Polling (quotes, the clock, orders) and downloads (the CSV export, statement
  PDFs) have to be initiated by the browser, but the browser must never learn
  the API's address or hold a bearer token. So the browser calls this route on
  our own origin, and this route attaches the caller's Clerk token server-side
  and forwards the request (Next.js 16 "Route Handlers" guide).

  Two rules make that safe:
    1. GET only. Every mutation goes through a Server Action, which React
       protects against cross-site invocation.
    2. An allowlist, not a passthrough. A wildcard proxy would let anyone who
       can reach this route call any API path the signed-in user can — including
       ones we never meant to expose.
*/

/*
  The API stamps every response with this (app/api/main.py). Recording it on
  our side of a failure is what makes a user's "it didn't load" joinable to the
  API's audit log — without it, the two halves of one broken request are two
  unrelated log lines.
*/
const REQUEST_ID = "x-request-id";

const ALLOWED: RegExp[] = [
  /^accounts\/me$/,
  /^market\/clock$/,
  /^market\/assets$/,
  /^market\/quotes\/[A-Za-z.]{1,10}$/,
  /^market\/bars\/[A-Za-z.]{1,10}$/,
  /^market\/token\/[A-Z.-]{1,16}$/,
  /^orders$/,
  /^orders\/[A-Za-z0-9-]{1,64}$/,
  /^positions$/,
  /^portfolio\/history$/,
  /^activities$/,
  /^activities\/export\.csv$/,
  /^documents$/,
  /^documents\/[A-Za-z0-9-]{1,64}\/download$/,
  /^pnl\/realized$/,
  /^pnl\/preview$/,
  /^weekend\/session$/,
  /^weekend\/preview$/,
  /^weekend\/orders$/,
  /^weekend\/orders\/\d{1,18}$/,
];

// Headers worth carrying back. Everything else (upstream auth, cookies, CORS)
// is dropped rather than relayed.
//
// X-Request-ID is relayed deliberately: it is the API's own handle on the call
// (see app/api/main.py), it names a row in the audit log, and it carries no
// information about anyone but the caller who just made the request.
const PASSTHROUGH = [
  "content-type",
  "content-disposition",
  "content-length",
  REQUEST_ID,
];

export async function GET(
  request: NextRequest,
  context: RouteContext<"/api/proxy/[...path]">,
) {
  const { path } = await context.params;
  const target = path.join("/");

  if (!ALLOWED.some((pattern) => pattern.test(target))) {
    console.error(`[proxy] blocked path=${target}`);
    return Response.json({ detail: "not_proxied" }, { status: 404 });
  }

  let upstream: Response;
  try {
    upstream = await forward("/" + target + request.nextUrl.search);
  } catch {
    // The API is not answering at all, so there is no request id to join on —
    // which is itself the finding: the call never reached the API.
    console.error(`[proxy] api unreachable path=${target}`);
    return Response.json({ detail: "unreachable" }, { status: 502 });
  }

  if (!upstream.ok) {
    // One flat string, not an object: log transports that serialise structured
    // arguments differently would otherwise drop the one field that matters.
    console.error(
      `[proxy] upstream error path=${target}` +
        ` status=${upstream.status}` +
        ` request_id=${upstream.headers.get(REQUEST_ID) ?? "none"}`,
    );
  }

  const headers = new Headers();
  for (const name of PASSTHROUGH) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  // A download the API did not label still has to arrive as a file.
  if (target.endsWith("export.csv") && !headers.has("content-disposition")) {
    headers.set("content-disposition", 'attachment; filename="yagnum-activity.csv"');
  }
  headers.set("cache-control", "no-store");

  return new Response(upstream.body, { status: upstream.status, headers });
}
