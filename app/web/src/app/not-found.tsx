import Link from "next/link";

import { buttonStyles } from "@/components/button";
import { Wordmark } from "@/components/wordmark";

export default function NotFound() {
  return (
    <main className="flex flex-1 items-center justify-center px-6 py-20">
      <div className="max-w-lg">
        <Wordmark />
        <h1 className="mt-6 font-display text-[2rem] leading-tight font-bold tracking-[-0.03em] text-ink">
          There&rsquo;s nothing at this address.
        </h1>
        <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">
          The page you asked for doesn&rsquo;t exist. Head back to the start.
        </p>
        <Link href="/" className={`${buttonStyles("primary")} mt-7`}>
          Go home
        </Link>
      </div>
    </main>
  );
}
