import metaFile from "../../data/meta.json";
import sponsorsFile from "../../data/sponsors.json";
import type { Meta, Placement, SponsorsFile } from "./types";

export const meta = metaFile as Meta;
export const sponsors = sponsorsFile as SponsorsFile;

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
