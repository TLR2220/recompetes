# Recompetes

Free directory of U.S. federal prime contractors and a **Recompete Radar**: large awards whose current end date is coming up, with the incumbent, agency, obligated amount, and end date.

The site is a static build. Search and filters run in the browser over JSON indexes, so GitHub Pages does not need a page per award or per notice.

## Local development

```bash
npm install
python3 scripts/update_data.py   # refresh the snapshot; safe to skip if data/ is already populated
npm run dev
```

The dev server is http://127.0.0.1:4817.

`npm test` runs the data-transform unit tests. `npm run build` writes `dist/`.

## Data sources

No API keys.

| Source | What it feeds | How |
| --- | --- | --- |
| [USAspending API](https://api.usaspending.gov) | Contractor, agency, and NAICS rankings; award histories; recipient address and business types; NAICS and set-aside on the largest radar rows | `POST /api/v2/search/spending_by_category/` and `/api/v2/search/spending_by_award/`, plus recipient and award detail GETs |
| [SAM.gov Contract Opportunities extract](https://sam.gov/data-services/) | Latest active notices | Public CSV, no key. The script streams and stops once it has the newest notices |

The committed files in `data/` are a real snapshot, so the first deploy is already populated.

What a profile is: one of the largest prime recipients in the obligation window. Award history is that company’s largest definitive contracts, delivery orders, BPA calls, and IDVs with an action since the date in the About page, not a complete FPDS archive. A recompete is one of those awards with at least $5 million obligated and a current end date (or last date to order, for a vehicle) inside 18 months. That is a signal, not a solicitation.

`data/sponsors.json` is hand-edited and is not overwritten by the data job.

## Daily job

`.github/workflows/daily.yml` runs at 12:20 UTC and on manual dispatch.

1. `python3 scripts/update_data.py` fetches each source on its own.
2. If a source errors, or comes back too thin to trust, the previous file for that source stays. The other source can still update.
3. Changed data files are committed as `Update federal contract data snapshot [data]` and pushed. That commit message stops the push from starting a second deploy.
4. The site is rebuilt and deployed to GitHub Pages.

SAM.gov usually publishes the extract around 04:30 UTC. A notice posted late in the U.S. day often shows up the next morning.

## Deploy to GitHub Pages

1. Push the repo to GitHub.
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Run the “Daily data and GitHub Pages” workflow once, or push to `main`.

The workflow calls `actions/configure-pages`, so a project site (`https://USER.github.io/REPO/`) gets the right base path and a custom domain gets `/`.

Override either value with repository **Variables** (Settings → Secrets and variables → Actions → Variables):

| Variable | Example | Effect |
| --- | --- | --- |
| `BASE_PATH` | `/recompetes` or `/` | Astro `base`. Leading slash, no trailing slash. |
| `SITE_URL` | `https://recompetes.com` | Canonical origin. No trailing slash. |

Local equivalents are `BASE_PATH` and `SITE_URL` in the environment, or a `.env` file. See `.env.example`.

### Custom domain

When DNS for `recompetes.com` points at GitHub Pages, set the custom domain in the Pages settings and set `SITE_URL` to `https://recompetes.com` and `BASE_PATH` to `/`. Do not commit a `CNAME` file until the domain is actually attached, or Pages will try to serve it early.

## Payments, alerts, and sponsors

All commercial settings live in `src/config.ts`.

- **Stripe**: replace the six `buy.stripe.com/placeholder_…` Payment Links. The pricing page says so while any URL still contains `placeholder`. Tiers are Claimed ($49/mo or $490/yr), Featured ($199/mo or $1,990/yr), and Radar sponsor ($599/mo or $5,990/yr). Annual is two months free.
- **Alerts**: set `alertsEndpoint` to a Formspree form, a Buttondown/ConvertKit action, or your own HTTPS endpoint that accepts a POST with `email`, `horizon`, `min_amount`, `naics`, and `agency`. An empty string keeps the form honest: it tells the visitor that delivery is not connected and stores nothing.
- **Contact**: `contactEmail` is the address on the claim and advertise pages. Fulfillment in v1 is email plus an edit, not an account.

Placements are `data/sponsors.json`:

```json
{
  "profiles": {
    "lockheed-martin-corporation-g4kdge": {
      "name": "Lockheed Martin",
      "url": "https://www.lockheedmartin.com",
      "blurb": "Short description in the company's words.",
      "tier": "featured"
    }
  },
  "radar": null,
  "agencies": {
    "department-of-veterans-affairs": {
      "name": "Sponsor name",
      "url": "https://example.com",
      "blurb": "Shown in the agency page slot."
    }
  },
  "naics": {}
}
```

`profiles` is keyed by the contractor page slug. `tier` is `claimed`, `featured`, or `sponsor`. Featured and sponsor profiles are pinned on the agency and NAICS pages where that contractor already has work, and they can appear on the homepage. `radar`, `agencies`, and `naics` fill the sponsored slot; a null or missing key renders the open-placement card. The next build publishes the change. The daily job does not touch this file.

## Pages

Home, Recompete Radar, contractor directory and profiles, agency pages, NAICS pages, SAM notices, search, claim/pricing, advertise, alerts, methodology, RSS (`/feed.xml`), `sitemap-index.xml`, and `robots.txt`.
