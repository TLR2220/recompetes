import { refreshDeadlines } from "./fresh";

function numberFrom(el: HTMLElement, name: string): number {
  const value = el.dataset[name];
  if (value == null || value === "") return Number.NaN;
  return Number(value);
}

function horizonOf(root: HTMLElement): number {
  const pressed = root.querySelector<HTMLElement>('[data-horizon-btn][aria-pressed="true"]');
  if (pressed?.dataset.horizonBtn) return Number(pressed.dataset.horizonBtn);
  const select = root.querySelector<HTMLSelectElement>("[data-filter-horizon]");
  return Number(select?.value || 0);
}

function compare(a: HTMLElement, b: HTMLElement, sort: string): number {
  const desc = !sort.endsWith("-asc");
  const key = sort.replace(/-asc|-desc/g, "");
  const dir = desc ? -1 : 1;
  if (key === "name") {
    return (a.dataset.name || "").localeCompare(b.dataset.name || "") * (desc ? 1 : -1) * -1 || dir;
  }
  if (key === "days" || key === "end") {
    return (numberFrom(a, "days") - numberFrom(b, "days")) * (desc ? -1 : 1);
  }
  if (key === "posted" || key === "deadline") {
    const av = a.dataset[key] || "";
    const bv = b.dataset[key] || "";
    return av.localeCompare(bv) * dir;
  }
  return (numberFrom(a, "amount") - numberFrom(b, "amount")) * dir;
}

export function applyFilters(root: HTMLElement): void {
  const query = (root.querySelector<HTMLInputElement>("[data-filter-q]")?.value || "").trim().toLowerCase();
  const agency = root.querySelector<HTMLSelectElement>("[data-filter-agency]")?.value || "";
  const sector = root.querySelector<HTMLSelectElement>("[data-filter-sector]")?.value || "";
  const type = root.querySelector<HTMLSelectElement>("[data-filter-type]")?.value || "";
  const setaside = root.querySelector<HTMLSelectElement>("[data-filter-setaside]")?.value || "";
  const state = root.querySelector<HTMLSelectElement>("[data-filter-state]")?.value || "";
  const horizon = horizonOf(root);
  const min = Number(root.querySelector<HTMLSelectElement>("[data-filter-min]")?.value || 0);
  const sort = root.querySelector<HTMLSelectElement>("[data-filter-sort]")?.value || "";
  const includePast = root.querySelector<HTMLInputElement>("[data-filter-past]")?.checked ?? false;
  const hasHorizon = Boolean(root.querySelector("[data-horizon-btn], [data-filter-horizon]"));
  const items = [...root.querySelectorAll<HTMLElement>("[data-item]")];
  let shown = 0;

  for (const el of items) {
    const text = (el.dataset.text || "").toLowerCase();
    const days = numberFrom(el, "days");
    const amount = numberFrom(el, "amount");
    let ok = true;
    if (query && !text.includes(query)) ok = false;
    if (agency && el.dataset.agency !== agency) ok = false;
    if (sector && el.dataset.sector !== sector) ok = false;
    if (state && el.dataset.state !== state) ok = false;
    if (setaside && el.dataset.setaside !== setaside) ok = false;
    if (type === "open" && el.dataset.open !== "1") ok = false;
    else if (type && type !== "open" && el.dataset.type !== type) ok = false;
    if (min && !Number.isNaN(amount) && amount < min) ok = false;
    if (hasHorizon && !Number.isNaN(days)) {
      if (horizon && days > horizon) ok = false;
      if (days < 0 && !includePast) ok = false;
    }
    el.hidden = !ok;
    if (ok) shown += 1;
  }

  if (sort) {
    const parent = items[0]?.parentElement;
    if (parent) {
      [...items]
        .sort((a, b) => compare(a, b, sort))
        .forEach((el) => parent.appendChild(el));
    }
  }

  const count = root.querySelector("[data-filter-count]");
  if (count) count.textContent = `${shown.toLocaleString("en-US")} shown`;
  const empty = root.querySelector<HTMLElement>("[data-filter-empty]");
  if (empty) empty.hidden = shown !== 0;
}

export function bindFilters(root: HTMLElement): void {
  refreshDeadlines(root);
  const run = () => applyFilters(root);
  root.querySelectorAll("input, select").forEach((el) => el.addEventListener("input", run));
  root.querySelectorAll("[data-horizon-btn]").forEach((button) => {
    button.addEventListener("click", () => {
      root.querySelectorAll("[data-horizon-btn]").forEach((other) => other.setAttribute("aria-pressed", "false"));
      button.setAttribute("aria-pressed", "true");
      run();
    });
  });
  run();
}
