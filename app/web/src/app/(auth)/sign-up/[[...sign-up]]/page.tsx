import type { Metadata } from "next";
import { SignUp } from "@clerk/nextjs";

import { clerkAppearance } from "@/components/clerk-appearance";

export const metadata: Metadata = { title: "Create an account" };

export default function SignUpPage() {
  return <SignUp appearance={clerkAppearance} />;
}
