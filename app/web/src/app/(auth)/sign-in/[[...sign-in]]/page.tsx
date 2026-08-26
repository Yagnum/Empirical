import type { Metadata } from "next";
import { SignIn } from "@clerk/nextjs";

import { clerkAppearance } from "@/components/clerk-appearance";

export const metadata: Metadata = { title: "Sign in" };

// Catch-all segment: Clerk routes its own multi-step flows (verification,
// factor two, reset) underneath /sign-in.
export default function SignInPage() {
  return <SignIn appearance={clerkAppearance} />;
}
