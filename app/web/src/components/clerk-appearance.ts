/**
 * Pulls Clerk's hosted UI onto Yagnum's palette and type so the sign-in screen
 * doesn't read as a third-party page bolted onto the product.
 */
export const clerkAppearance = {
  variables: {
    colorPrimary: "#15467e",
    colorForeground: "#10233a",
    colorMutedForeground: "#57647a",
    colorBackground: "#ffffff",
    colorInput: "#ffffff",
    colorDanger: "#a32b24",
    borderRadius: "8px",
    fontFamily: "var(--font-public-sans), ui-sans-serif, system-ui, sans-serif",
  },
  elements: {
    cardBox: "shadow-card border border-rule-soft rounded-card",
    card: "shadow-none",
    footer: "bg-transparent",
  },
};
