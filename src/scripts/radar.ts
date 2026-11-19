interface Row {
  award_id?: string;
  slug: string;
  incumbent: string;
  description: string;
  amount: number;
  agency: string;
  agency_slug?: string;
  naics?: string;
  naics_name?: string;
  state?: string;
  end: string;
  days: number;
  type?: string;
  tags?: string[];
  set_aside_bucket?: string;
}

const PAGE = 40;

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function money(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function daysOf(iso: string): number {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!match) return 99999;
  const end = Date.UTC(+match[1], +match[2] - 1, +match[3]);
  const now = new Date();
  const start = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((end - start) / 86_400_000);
}

function urgency(days: number): string {
  if (days < 0) return "past";
  if (days <= 45) return "soon";
  if (days <= 120) return "near";
  return "later";
}

export async function mountRadar(root: HTMLElement): Promise<void> {
  const base = root.dataset.base || "/";
  const version = root.dataset.version || "";
  const status = root.querySelector<HTMLElement>("[data-radar-status]")!;
  const body = root.querySelector<HTMLElement>("[data-radar-body]")!;
  const pager = root.querySelector<HTMLElement>("[data-radar-pager]")!;
  status.textContent = "Loading the radar…";
  let rows: Row[] = [];
  try {
    const payload = await fetch(`${base}data/recompetes.json?v=${encodeURIComponent(version)}`).then((res) => res.json());
    rows = (payload.recompetes || []).map((row: Row) => ({ ...row, days: daysOf(row.end) }));
  } catch {
    status.textContent = "The radar file could not be loaded.";
    return;
  }

  const agency = root.querySelector<HTMLSelectElement>("[data-filter-agency]")!;
  const state = root.querySelector<HTMLSelectElement>("[data-filter-state]")!;
  const tag = root.querySelector<HTMLSelectElement>("[data-filter-setaside]")!;
  const agencies = [...new Set(rows.map((row) => row.agency).filter(Boolean))].sort();
  const states = [...new Set(rows.map((row) => row.state).filter(Boolean) as string[])].sort();
  for (const name of agencies) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    agency.append(option);
  }
  for (const code of states) {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = code;
    state.append(option);
  }

  let page = 0;
  const filtered = () => {
    const q = (root.querySelector<HTMLInputElement>("[data-filter-q]")?.value || "").trim().toLowerCase();
    const naics = (root.querySelector<HTMLInputElement>("[data-filter-naics]")?.value || "").trim();
    const horizon = Number(root.querySelector<HTMLSelectElement>("[data-filter-horizon]")?.value || "540");
    const min = Number(root.querySelector<HTMLSelectElement>("[data-filter-min]")?.value || "0");
    const past = root.querySelector<HTMLInputElement>("[data-filter-past]")?.checked ?? false;
    const sort = root.querySelector<HTMLSelectElement>("[data-filter-sort]")?.value || "days";
    let list = rows.filter((row) => {
      if (q && !`${row.description} ${row.incumbent} ${row.agency} ${row.award_id || ""} ${row.naics || ""}`.toLowerCase().includes(q)) return false;
      if (agency.value && row.agency !== agency.value) return false;
      if (state.value && row.state !== state.value) return false;
      if (tag.value && !(row.tags || []).includes(tag.value) && row.set_aside_bucket !== tag.value) return false;
      if (naics && !(row.naics || "").startsWith(naics)) return false;
      if (row.amount < min) return false;
      if (row.days > horizon) return false;
      if (row.days < 0 && !past) return false;
      return true;
    });
    list.sort((a, b) => {
      if (sort === "amount") return b.amount - a.amount;
      if (sort === "agency") return a.agency.localeCompare(b.agency) || a.days - b.days;
      if (sort === "state") return (a.state || "").localeCompare(b.state || "") || a.days - b.days;
      return a.days - b.days || b.amount - a.amount;
    });
    return list;
  };

  const draw = () => {
    const list = filtered();
    const pages = Math.max(1, Math.ceil(list.length / PAGE));
    page = Math.min(page, pages - 1);
    const slice = list.slice(page * PAGE, page * PAGE + PAGE);
    status.textContent = `${list.length.toLocaleString("en-US")} awards · page ${page + 1} of ${pages}`;
    body.innerHTML = slice
      .map((row) => {
        const who = row.slug ? `<a href="${base}contractors/${row.slug}/">${escapeHtml(row.incumbent)}</a>` : escapeHtml(row.incumbent);
        const label = row.days < 0 ? `${Math.abs(row.days)}d ago` : row.days === 0 ? "Today" : `${row.days}d`;
        return `<tr data-urgency="${urgency(row.days)}">
          <td data-label="Contract"><div class="desc">${escapeHtml(row.description)}</div><div class="meta-line">${escapeHtml([row.type, row.award_id, row.naics ? `NAICS ${row.naics}` : "", row.state].filter(Boolean).join(" · "))}</div></td>
          <td data-label="Incumbent">${who}</td>
          <td data-label="Agency">${escapeHtml(row.agency)}</td>
          <td class="num" data-label="Obligated">${money(row.amount)}</td>
          <td class="num" data-label="End">${escapeHtml(row.end)}</td>
          <td data-label="Left"><span class="days-pill">${label}</span></td>
        </tr>`;
      })
      .join("");
    pager.innerHTML = `<button type="button" data-nav="prev" ${page === 0 ? "disabled" : ""}>Previous</button><span>${(page * PAGE + 1).toLocaleString("en-US")}–${Math.min(list.length, page * PAGE + PAGE).toLocaleString("en-US")}</span><button type="button" data-nav="next" ${page >= pages - 1 ? "disabled" : ""}>Next</button>`;
  };

  root.querySelectorAll("input, select").forEach((el) =>
    el.addEventListener("input", () => {
      page = 0;
      draw();
    }),
  );
  pager.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest("button");
    if (!button || button.hasAttribute("disabled")) return;
    page += button.dataset.nav === "next" ? 1 : -1;
    draw();
    root.scrollIntoView({ block: "start" });
  });
  draw();
}
