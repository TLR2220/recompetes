export function bindPricing(root: HTMLElement): void {
  const buttons = [...root.querySelectorAll<HTMLButtonElement>("[data-billing]")];
  const apply = (mode: string) => {
    root.dataset.billing = mode;
    buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.billing === mode)));
    root.querySelectorAll<HTMLElement>("[data-price]").forEach((el) => {
      el.hidden = el.dataset.price !== mode;
    });
  };
  buttons.forEach((button) => button.addEventListener("click", () => apply(button.dataset.billing || "annual")));
  apply(root.dataset.billing || "annual");
}
