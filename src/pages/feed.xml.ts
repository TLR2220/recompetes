import type { APIRoute } from "astro";
import { meta, opportunities, recompetes } from "../lib/data";
import { openNotice } from "../lib/format";
import { absolute } from "../lib/url";

export const prerender = true;

function xml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export const GET: APIRoute = () => {
  const updated = new Date(meta.generated_at).toUTCString();
  const radar = recompetes.filter((row) => row.days >= 0).slice(0, 25);
  const notices = opportunities.filter((row) => openNotice(row.type)).slice(0, 15);
  const items = [
    ...radar.map((row) => ({
      title: `${row.incumbent}: ${row.description}`,
      link: absolute(`contractors/${row.slug}/`),
      guid: row.generated_id || `${row.slug}-${row.award_id}`,
      date: updated,
      description: `${row.agency}. ${row.amount.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })} obligated. Current end ${row.end}. ${row.days} days out.`,
    })),
    ...notices.map((row) => ({
      title: row.title,
      link: row.link,
      guid: row.id,
      date: row.posted ? new Date(`${row.posted}T00:00:00Z`).toUTCString() : updated,
      description: `${row.type} · ${row.agency}. ${row.description}`,
    })),
  ];
  const body = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Recompetes radar</title>
    <link>${xml(absolute())}</link>
    <description>Large federal awards coming to an end, plus the newest SAM.gov notices.</description>
    <language>en-us</language>
    <lastBuildDate>${updated}</lastBuildDate>
    ${items
      .map(
        (item) => `<item>
      <title>${xml(item.title)}</title>
      <link>${xml(item.link)}</link>
      <guid isPermaLink="false">${xml(item.guid)}</guid>
      <pubDate>${item.date}</pubDate>
      <description>${xml(item.description)}</description>
    </item>`,
      )
      .join("\n")}
  </channel>
</rss>`;
  return new Response(body, { headers: { "Content-Type": "application/rss+xml; charset=utf-8" } });
};
