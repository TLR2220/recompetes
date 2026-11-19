/**
 * Commercial settings for Recompetes.
 *
 * Replace the Stripe Payment Link placeholders before charging anyone.
 * Point alertsEndpoint at Formspree, Buttondown, ConvertKit, or your own
 * endpoint. Leave it empty and the form explains that delivery is not connected.
 * Fulfill placements by editing data/sponsors.json — see the README.
 */
export const contactEmail = "hello@recompetes.com";

export const alertsEndpoint = "";

export const stripe = {
  claimMonthly: "https://buy.stripe.com/placeholder_claim_monthly",
  claimAnnual: "https://buy.stripe.com/placeholder_claim_annual",
  featuredMonthly: "https://buy.stripe.com/placeholder_featured_monthly",
  featuredAnnual: "https://buy.stripe.com/placeholder_featured_annual",
  sponsorMonthly: "https://buy.stripe.com/placeholder_sponsor_monthly",
  sponsorAnnual: "https://buy.stripe.com/placeholder_sponsor_annual",
} as const;

export type TierId = "claim" | "featured" | "sponsor";

export interface Tier {
  id: TierId;
  name: string;
  kicker: string;
  monthly: number;
  annual: number;
  monthlyUrl: string;
  annualUrl: string;
  featured?: boolean;
  points: string[];
}

export const tiers: Tier[] = [
  {
    id: "claim",
    name: "Claimed",
    kicker: "Your listing, in your words",
    monthly: 49,
    annual: 490,
    monthlyUrl: stripe.claimMonthly,
    annualUrl: stripe.claimAnnual,
    points: [
      "Claimed badge on your contractor page",
      "Website link and a short description you write",
      "Shown as claimed in directory search",
      "A direct way to correct the public record",
    ],
  },
  {
    id: "featured",
    name: "Featured",
    kicker: "Where capture teams start",
    monthly: 199,
    annual: 1990,
    monthlyUrl: stripe.featuredMonthly,
    annualUrl: stripe.featuredAnnual,
    featured: true,
    points: [
      "Everything in Claimed",
      "Featured badge on your page and directory card",
      "Pinned to the top of your primary agency and NAICS pages",
      "Eligible for the homepage feature row",
    ],
  },
  {
    id: "sponsor",
    name: "Radar sponsor",
    kicker: "One placement, in context",
    monthly: 599,
    annual: 5990,
    monthlyUrl: stripe.sponsorMonthly,
    annualUrl: stripe.sponsorAnnual,
    points: [
      "Everything in Featured",
      "Sponsored unit on the Recompete Radar",
      "One agency page or one NAICS page sponsorship",
      "A mention in the recompete alert when that list is sending",
    ],
  },
];

export function paymentsArePlaceholders(): boolean {
  return Object.values(stripe).some((url) => url.includes("placeholder"));
}
