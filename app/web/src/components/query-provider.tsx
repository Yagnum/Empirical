"use client";

import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/*
  TanStack Query, mounted once for the signed-in shell (ADR-012).

  The client is created inside state rather than at module scope so a server
  render never shares one cache between two users' requests — the standard
  Next.js App Router setup.
*/
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Every figure here is a live market or account value. Individual
            // queries set their own poll interval; none of them may serve a
            // stale number without asking first.
            staleTime: 0,
            // One retry, then show the error state. A trader would rather see
            // "this didn't load" than a spinner that never resolves.
            retry: 1,
            refetchOnWindowFocus: true,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
