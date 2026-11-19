import metaFile from "../../data/meta.json";
import contractorsFile from "../../data/contractors.json";
import agenciesFile from "../../data/agencies.json";
import naicsFile from "../../data/naics.json";
import recompetesFile from "../../data/recompetes.json";
import opportunitiesFile from "../../data/opportunities.json";
import sponsorsFile from "../../data/sponsors.json";
import type {
  Agency,
  Contractor,
  Meta,
  NaicsPage,
  Opportunity,
  Placement,
  Recompete,
  SponsorsFile,
} from "./types";

export const meta = metaFile as Meta;
export const contractors = (contractorsFile as { contractors: Contractor[] }).contractors;
export const agencies = (agenciesFile as { agencies: Agency[] }).agencies;
export const naicsPages = (naicsFile as { naics: NaicsPage[] }).naics;
export const recompetes = (recompetesFile as { recompetes: Recompete[] }).recompetes;
export const opportunities = (opportunitiesFile as { opportunities: Opportunity[] }).opportunities;
export const sponsors = sponsorsFile as SponsorsFile;

export const contractorBySlug = new Map(contractors.map((contractor) => [contractor.slug, contractor]));

export function profileOf(slug: string): Placement | null {
  return sponsors.profiles[slug] ?? null;
}

export function tierRank(slug: string): number {
  const tier = profileOf(slug)?.tier;
  if (tier === "sponsor") return 0;
  if (tier === "featured") return 1;
  if (tier === "claimed") return 2;
  return 3;
}

export function upcomingRecompetes(): Recompete[] {
  return recompetes.filter((row) => row.days >= 0);
}

export function featuredContractors(): Contractor[] {
  return contractors
    .filter((contractor) => {
      const tier = profileOf(contractor.slug)?.tier;
      return tier === "featured" || tier === "sponsor";
    })
    .sort((a, b) => tierRank(a.slug) - tierRank(b.slug) || b.total_obligations - a.total_obligations);
}
