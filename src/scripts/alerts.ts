export function bindAlerts(form: HTMLFormElement): void {
  const message = form.querySelector<HTMLElement>("[data-form-msg]");
  form.addEventListener("submit", (event) => {
    const honeypot = form.querySelector<HTMLInputElement>("[name='company_website']");
    if (honeypot?.value) {
      event.preventDefault();
      return;
    }
    const endpoint = form.dataset.endpoint || "";
    if (!endpoint) {
      event.preventDefault();
      if (message) {
        message.textContent = "Alert delivery is not connected yet. Set alertsEndpoint in src/config.ts. This address was not stored.";
        message.classList.add("show");
      }
    }
  });
}
