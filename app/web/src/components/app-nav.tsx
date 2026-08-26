"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/*
  Four places, in the order a trader moves through them: look at what you hold,
  buy or sell something, watch the order work, read the record afterwards.

  The active section is marked by a rule under the label, not a filled pill —
  it is the same hairline vocabulary the rest of the interface is set in.
*/
const SECTIONS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/trade", label: "Trade" },
  { href: "/orders", label: "Orders" },
  { href: "/history", label: "History" },
];

export function AppNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Sections"
      // On a phone this wraps onto its own row under the wordmark; from `sm`
      // up it sits inline between the wordmark and the account button.
      className="order-3 -mx-6 w-full overflow-x-auto px-6 sm:order-2 sm:mx-0 sm:w-auto sm:flex-1 sm:overflow-visible sm:px-0"
    >
      <ul className="flex items-center gap-6 sm:gap-7">
        {SECTIONS.map((section) => {
          // /trade/AAPL is still the Trade section.
          const active =
            pathname === section.href || pathname.startsWith(section.href + "/");

          return (
            <li key={section.href}>
              <Link
                href={section.href}
                aria-current={active ? "page" : undefined}
                className={`inline-flex h-11 items-center border-b-2 font-display text-[14px] whitespace-nowrap transition-colors sm:h-16 ${
                  active
                    ? "border-accent font-semibold text-ink"
                    : "border-transparent font-medium text-ink-soft hover:border-rule hover:text-ink"
                }`}
              >
                {section.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
