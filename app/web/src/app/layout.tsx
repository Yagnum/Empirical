import type { Metadata } from "next";
import { Public_Sans, Schibsted_Grotesk, Source_Serif_4 } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

// Public Sans is the typeface of the U.S. Web Design System — built to be
// read in public-trust interfaces. It carries all UI copy and small figures.
const publicSans = Public_Sans({
  variable: "--font-public-sans",
  subsets: ["latin"],
  display: "swap",
});

// Schibsted Grotesk carries every headline. It shares Public Sans' grotesk
// skeleton, so the page reads as one voice, but its tighter fit and squarer
// terminals give display sizes a spine that Public Sans alone doesn't have.
const schibsted = Schibsted_Grotesk({
  variable: "--font-schibsted",
  subsets: ["latin"],
  display: "swap",
});

// Source Serif 4 now appears in exactly two places: the wordmark, and the one
// hero money figure per screen. Serif = "this is the authoritative number".
const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Yagnum — practice the market with simulated money",
    template: "%s · Yagnum",
  },
  description:
    "Yagnum is a paper-trading brokerage account: place trades against real U.S. market prices with simulated money, with nothing at stake.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  // Clerk's current App Router quickstart mounts ClerkProvider inside <body>
  // rather than around <html>, so the document shell stays server-rendered.
  return (
    <html
      lang="en"
      className={`${publicSans.variable} ${schibsted.variable} ${sourceSerif.variable} h-full`}
    >
      <body className="flex min-h-full flex-col">
        <ClerkProvider>{children}</ClerkProvider>
      </body>
    </html>
  );
}
