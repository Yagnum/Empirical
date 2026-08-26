import { orderStatusLabel, orderStatusTone, type StatusTone } from "@/lib/orders";

/*
  An order's state, as a chip.

  Only two of the four tones carry colour: the one that is still live, and the
  one that went wrong. A filled or cancelled order is finished, and finished is
  not news — it reads in plain ink. Keeping the palette this quiet is what lets
  a single red chip in a long list actually mean something.
*/

const TONES: Record<StatusTone, string> = {
  working: "border-accent/25 bg-accent-wash text-accent",
  filled: "border-rule bg-paper text-ink",
  ended: "border-rule bg-paper text-ink-faint",
  refused: "border-loss/30 bg-loss/8 text-loss",
};

export function OrderStatus({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-[3px] text-[11px] leading-none font-semibold whitespace-nowrap ${TONES[orderStatusTone(status)]}`}
    >
      {orderStatusLabel(status)}
    </span>
  );
}
