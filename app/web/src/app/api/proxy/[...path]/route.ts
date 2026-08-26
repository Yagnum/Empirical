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

const ALLOWED: RegExp[] = [
  /^accounts\/me$/,
  /^market\/clock$/,
  /^market\/assets$/,
  /^market\/quotes\/[A-Za-z.]{1,10}$/,
  /^market\/bars\/[A-Za-z.]{1,10}$/,
  /^orders$/,
  /^orders\/[A-Za-z0-9-]{1,64}$/,
  /^positions$/,
  /^portfolio\/history$/,
  /^activities$/,
  /^activities\/export\.csv$/,
  /^documents$/,
  /^documents\/[A-Za-z0-9-]{1,64}\/download$/,
];

// Headers worth carrying back. Everything else (upstream auth, cookies, CORS)
// is dropped rather than relayed.
const PASSTHROUGH = ["content-type", "content-disposition", "content-length"];

export async function GET(
  request: NextRequest,
  context: RouteContext<"/api/proxy/[...path]">,
) {
  const { path } = await context.params;
  const target = path.join("/");

  if (!ALLOWED.some((pattern) => pattern.test(target))) {
    return Response.json({ detail: "not_proxied" }, { status: 404 });
  }

  let upstream: Response;
  try {
    upstream = await forward("/" + target + request.nextUrl.search);
  } catch {
    // The API is not answering at all. Say so in the shape the client's error
    // handling already understands.
    return Response.json({ detail: "unreachable" }, { status: 502 });
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
