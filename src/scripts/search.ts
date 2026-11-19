interface SlimContractor {
  slug: string;
  name: string;
  uei: string;
  state: string;
  amount: number;
  profiled: boolean;
  top_naics: string;
  top_agency: string;
  usaspending_url: string;
}
interface SlimAgency { slug: string; name: string; amount: number; code: string; }
interface SlimNaics { code: string; name: string; amount: number; sector: string; }
interface RecompeteHit {
  slug: string;
  incumbent: string;
  description: string;
  agency: string;
  amount: number;
  end: string;
  naics: string;
  award_id: string;
}
interface NoticeHit {
  id: string;
  title: string;
  agency: string;
  naics: string;
  type: string;
  posted: string;
  link: string;
  solicitation: string;
}

const money = (value: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(value);

function includes(q: string, ...fields: Array<string | undefined>): boolean {
  const hay = fields.filter(Boolean).join(" ").toLowerCase();
  return hay.includes(q);
}

export async function runSearch(root: HTMLElement): Promise<void> {
  const base = root.dataset.base || "/";
  const version = root.dataset.version || "";
  const output = root.querySelector<HTMLElement>("[data-search-results]")!;
  const status = root.querySelector<HTMLElement>("[data-search-status]")!;
  const input = root.querySelector<HTMLInputElement>("#site-search")!;
  const url = new URL(window.location.href);
  if (url.searchParams.get("q")) input.value = url.searchParams.get("q") || "";

  status.textContent = "Loading the directory index…";
  let contractors: SlimContractor[] = [];
  let agencies: SlimAgency[] = [];
  let naics: SlimNaics[] = [];
  let recompetes: RecompeteHit[] = [];
  let notices: NoticeHit[] = [];
  try {
    const bust = version ? `?v=${encodeURIComponent(version)}` : "";
    const [index, radar, opps] = await Promise.all([
      fetch(`${base}data/index.json${bust}`).then((r) => r.json()),
      fetch(`${base}data/recompetes.json${bust}`).then((r) => r.json()),
      fetch(`${base}data/opportunities.json${bust}`).then((r) => r.json()),
    ]);
    contractors = index.contractors || [];
    agencies = index.agencies || [];
    naics = index.naics || [];
    recompetes = radar.recompetes || [];
    notices = opps.opportunities || [];
  } catch {
    status.textContent = "The directory index could not be loaded. Refresh the page.";
    return;
  }

  const render = () => {
    const q = input.value.trim().toLowerCase();
    const params = new URLSearchParams(window.location.search);
    if (q) params.set("q", q);
    else params.delete("q");
    const next = `${window.location.pathname}${params.toString() ? `?${params}` : ""}`;
    window.history.replaceState(null, "", next);
    if (q.length < 2) {
      status.textContent = "Type at least two characters.";
      output.innerHTML = "";
      return;
    }
    const groups: string[] = [];
    const firmHits = contractors.filter((row) => includes(q, row.name, row.uei, row.state, row.top_naics, row.top_agency)).slice(0, 12);
    const agencyHits = agencies.filter((row) => includes(q, row.name, row.code)).slice(0, 8);
    const naicsHits = naics.filter((row) => includes(q, row.code, row.name, row.sector)).slice(0, 8);
    const radarHits = recompetes.filter((row) => includes(q, row.incumbent, row.description, row.agency, row.naics, row.award_id)).slice(0, 8);
    const noticeHits = notices.filter((row) => includes(q, row.title, row.agency, row.naics, row.solicitation, row.type)).slice(0, 8);

    const block = (title: string, html: string) => {
      if (!html) return;
      groups.push(`<section><h2>${title}</h2><div class="stack">${html}</div></section>`);
    };
    block(
      "Contractors",
      firmHits
        .map((row) => {
          const href = row.profiled ? `${base}contractors/${row.slug}/` : row.usaspending_url;
          const extra = row.profiled ? "Profile" : "USAspending";
          return `<a class="card" href="${href}" ${row.profiled ? "" : 'target="_blank" rel="noopener noreferrer"'}>
            <h3>${escapeHtml(row.name)}</h3>
            <div class="amount num">${money(row.amount)}</div>
            <p class="meta-line">${escapeHtml([row.state, row.top_agency, row.top_naics].filter(Boolean).join(" · ") || extra)}</p>
          </a>`;
        })
        .join(""),
    );
    block(
      "Agencies",
      agencyHits
        .map((row) => `<a class="card" href="${base}agencies/${row.slug}/"><h3>${escapeHtml(row.name)}</h3><div class="amount num">${money(row.amount)}</div><p class="meta-line">Contract obligations in the tracked window</p></a>`)
        .join(""),
    );
    block(
      "NAICS",
      naicsHits
        .map((row) => `<a class="card" href="${base}naics/${row.code}/"><h3>${escapeHtml(row.code)} · ${escapeHtml(row.name)}</h3><div class="amount num">${money(row.amount)}</div><p class="meta-line">${escapeHtml(row.sector)}</p></a>`)
        .join(""),
    );
    block(
      "Recompetes",
      radarHits
        .map((row) => `<a class="card" href="${base}contractors/${row.slug}/"><h3>${escapeHtml(row.description)}</h3><p class="meta-line">${escapeHtml(row.incumbent)} · ${escapeHtml(row.agency)}</p><div class="amount num">${money(row.amount)}</div><p class="meta-line">Ends ${escapeHtml(row.end)}</p></a>`)
        .join(""),
    );
    block(
      "SAM notices",
      noticeHits
        .map((row) => `<a class="card" href="${escapeHtml(row.link)}" target="_blank" rel="noopener noreferrer"><h3>${escapeHtml(row.title)}</h3><p class="meta-line">${escapeHtml(row.type)} · ${escapeHtml(row.agency)}</p><p class="meta-line">Posted ${escapeHtml(row.posted || "—")}</p></a>`)
        .join(""),
    );
    const total = firmHits.length + agencyHits.length + naicsHits.length + radarHits.length + noticeHits.length;
    status.textContent = total ? `${total.toLocaleString("en-US")} matches` : "No matches in this snapshot.";
    output.innerHTML = groups.join("");
  };

  root.querySelector("form")?.addEventListener("submit", (event) => event.preventDefault());
  input.addEventListener("input", render);
  render();
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
