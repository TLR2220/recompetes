interface Row {
  slug: string;
  name: string;
  uei?: string;
  state?: string;
  amount: number;
  profiled: boolean;
  tags?: string[];
  top_agency?: string;
  small_business?: boolean;
}

const PAGE = 24;

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function money(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export async function mountDirectory(root: HTMLElement): Promise<void> {
  const base = root.dataset.base || "/";
  const version = root.dataset.version || "";
  const status = root.querySelector<HTMLElement>("[data-dir-status]")!;
  const grid = root.querySelector<HTMLElement>("[data-dir-grid]")!;
  const pager = root.querySelector<HTMLElement>("[data-dir-pager]")!;
  const stateSelect = root.querySelector<HTMLSelectElement>("[data-filter-state]")!;
  let rows: Row[] = [];
  try {
    const payload = await fetch(`${base}data/index.json?v=${encodeURIComponent(version)}`).then((res) => res.json());
    rows = (payload.contractors || []).filter((row: Row) => row.profiled && row.slug);
  } catch {
    status.textContent = "The contractor index could not be loaded.";
    return;
  }
  const states = [...new Set(rows.map((row) => row.state).filter(Boolean) as string[])].sort();
  for (const code of states) {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = code;
    stateSelect.append(option);
  }
  let page = 0;
  const filtered = () => {
    const q = (root.querySelector<HTMLInputElement>("[data-filter-q]")?.value || "").trim().toLowerCase();
    const tag = root.querySelector<HTMLSelectElement>("[data-filter-setaside]")?.value || "";
    const sort = root.querySelector<HTMLSelectElement>("[data-filter-sort]")?.value || "amount";
    let list = rows.filter((row) => {
      if (q && !`${row.name} ${row.uei || ""} ${row.top_agency || ""} ${(row.tags || []).join(" ")}`.toLowerCase().includes(q)) return false;
      if (stateSelect.value && row.state !== stateSelect.value) return false;
      if (tag && !(row.tags || []).includes(tag)) return false;
      return true;
    });
    list.sort((a, b) => (sort === "name" ? a.name.localeCompare(b.name) : b.amount - a.amount));
    return list;
  };
  const draw = () => {
    const list = filtered();
    const pages = Math.max(1, Math.ceil(list.length / PAGE));
    page = Math.min(page, pages - 1);
    const slice = list.slice(page * PAGE, page * PAGE + PAGE);
    status.textContent = `${list.length.toLocaleString("en-US")} profiles · page ${page + 1} of ${pages}`;
    grid.innerHTML = slice
      .map((row) => {
        const tags = (row.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
        return `<a class="card" href="${base}contractors/${row.slug}/"><h3>${escapeHtml(row.name)}</h3><div class="amount num">${money(row.amount)}</div><p class="meta-line">${escapeHtml(row.state || "State not on the record")}${row.top_agency ? ` · ${escapeHtml(row.top_agency)}` : ""}</p><div class="tags">${tags}</div></a>`;
      })
      .join("");
    pager.innerHTML = `<button type="button" data-nav="prev" ${page === 0 ? "disabled" : ""}>Previous</button><span>${page + 1} / ${pages}</span><button type="button" data-nav="next" ${page >= pages - 1 ? "disabled" : ""}>Next</button>`;
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
  });
  draw();
}
