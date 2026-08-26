import Link from "next/link";

/**
 * The Yagnum wordmark — one of only two places the serif is still allowed
 * (the other is a screen's hero money figure). It anchors the brand while
 * everything around it speaks grotesk.
 */
export function Wordmark({ href = "/" }: { href?: string }) {
  return (
    <Link
      href={href}
      className="font-serif text-[1.375rem] leading-none font-semibold tracking-[-0.015em] text-ink"
    >
      Yagnum
    </Link>
  );
}
