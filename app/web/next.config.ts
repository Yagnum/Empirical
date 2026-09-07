import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // "standalone" makes `next build` emit .next/standalone: a self-contained
  // server.js plus only the node_modules it needs. That is what the Azure
  // deploy ships (docs/AZURE-DEPLOY.md) - built in GitHub Actions, zipped,
  // started with `node server.js`. The Free tier's 1 GB has no room to run
  // a Next.js build itself.
  output: "standalone",
};

export default nextConfig;
