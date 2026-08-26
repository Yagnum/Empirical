import { clerkMiddleware } from "@clerk/nextjs/server";

/*
  Next.js 16 renamed Middleware to Proxy. The file must sit beside `app/` —
  because this project uses a `src/` directory, that means `src/proxy.ts`
  (node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md).

  This runs clerkMiddleware() and nothing else. It exists so `auth()` is
  available inside Server Components and Server Actions — it does NOT decide
  who may see what. Clerk deprecated route-matcher gating in the proxy because
  path patterns can drift from how Next.js actually routes a request; the real
  checks live next to the data, in the protected pages themselves.
*/
export default clerkMiddleware();

export const config = {
  matcher: [
    // Everything except Next internals and static files...
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // ...plus API routes.
    "/(api|trpc)(.*)",
  ],
};
