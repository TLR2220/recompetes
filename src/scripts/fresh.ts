export function refreshDeadlines(root: ParentNode = document): void {
  const now = new Date();
  const start = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  root.querySelectorAll<HTMLElement>("[data-end]").forEach((el) => {
    const end = el.dataset.end;
    if (!end) return;
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(end);
    if (!match) return;
    const when = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    const days = Math.round((when - start) / 86_400_000);
    el.dataset.days = String(days);
    const label = el.querySelector("[data-days-label]");
    if (label) {
      label.textContent = days === 0 ? "Today" : days < 0 ? `${Math.abs(days)}d ago` : `${days}d`;
    }
    const urgency = days < 0 ? "past" : days <= 45 ? "soon" : days <= 120 ? "near" : "later";
    el.dataset.urgency = urgency;
  });
}
