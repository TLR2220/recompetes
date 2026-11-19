const SECTORS: Record<string, string> = {
  "11": "Agriculture",
  "21": "Mining and energy",
  "22": "Utilities",
  "23": "Construction",
  "31": "Manufacturing",
  "32": "Manufacturing",
  "33": "Manufacturing",
  "42": "Wholesale",
  "44": "Retail",
  "45": "Retail",
  "48": "Transportation",
  "49": "Transportation",
  "51": "Information",
  "52": "Finance",
  "53": "Real estate",
  "54": "Professional services",
  "55": "Management",
  "56": "Administrative",
  "61": "Education",
  "62": "Health care",
  "71": "Arts and recreation",
  "72": "Hospitality",
  "81": "Other services",
  "92": "Public administration",
};

export function money(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  const sign = n < 0 ? "−" : "";
  const abs = Math.abs(n);
  const fmt = (v: number, digits: number) =>
    v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  if (abs >= 1_000_000_000_000) return `${sign}$${fmt(abs / 1e12, 2)}T`;
  if (abs >= 1_000_000_000) return `${sign}$${fmt(abs / 1e9, 2)}B`;
  if (abs >= 1_000_000) return `${sign}$${fmt(abs / 1e6, 1)}M`;
  if (abs >= 10_000) return `${sign}$${fmt(abs / 1e3, 0)}K`;
  return `${sign}$${fmt(abs, 0)}`;
}

export function moneyFull(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function prettyDate(iso?: string | null): string {
  if (!iso) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const dt = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export function daysUntil(iso?: string | null, today = new Date()): number | null {
  if (!iso) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return null;
  const end = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const start = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.round((end - start) / 86_400_000);
}

export function daysLabel(days: number | null): string {
  if (days == null) return "—";
  if (days === 0) return "Today";
  if (days < 0) return `${Math.abs(days)}d ago`;
  return `${days}d`;
}

export function urgency(days: number | null): "past" | "soon" | "near" | "later" | "none" {
  if (days == null) return "none";
  if (days < 0) return "past";
  if (days <= 45) return "soon";
  if (days <= 120) return "near";
  return "later";
}

export function sectorName(code?: string | null): string {
  if (!code) return "";
  return SECTORS[code.slice(0, 2)] || "Other";
}

export function place(location?: { city?: string; state?: string; country?: string } | null): string {
  if (!location) return "";
  const city = location.city || "";
  const state = location.state || "";
  if (city && state) return `${city}, ${state}`;
  if (state) return state;
  return location.country || "";
}

export function freshLabel(iso?: string | null): string {
  if (!iso) return "Updated daily";
  return `Updated ${prettyDate(iso)}`;
}

export function openNotice(type: string): boolean {
  return [
    "Solicitation",
    "Presolicitation",
    "Sources Sought",
    "Combined Synopsis/Solicitation",
    "Special Notice",
  ].includes(type);
}

export function jsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
