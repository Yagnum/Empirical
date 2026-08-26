/**
 * One place that decides what a button looks like, shared by <button> and
 * <Link> so a link that acts like a button never drifts visually from one.
 */
export type ButtonVariant = "primary" | "secondary" | "quiet";

const base =
  "inline-flex items-center justify-center rounded-control px-5 py-2.5 font-display text-[15px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55";

const variants: Record<ButtonVariant, string> = {
  // Hover lifts toward a brighter blue rather than darkening — reads as
  // responsive rather than heavy, and still clears AA on white text.
  primary: "bg-accent text-white hover:bg-accent-bright active:bg-accent-deep",
  secondary:
    "border border-rule bg-surface text-ink hover:border-ink-faint hover:bg-paper",
  quiet: "text-accent hover:text-accent-bright",
};

export function buttonStyles(variant: ButtonVariant = "primary") {
  return `${base} ${variants[variant]}`;
}
