export interface Award {
  id: string;
  generated_id: string;
  description: string;
  amount: number;
  agency: string;
  agency_slug: string;
  subagency: string;
  naics: string;
  naics_name: string;
  psc: string;
  psc_name: string;
  start: string;
  end: string;
  potential_end: string;
  type: string;
  set_aside: string;
  extent_competed: string;
  usaspending_url: string;
}

export interface NamedAmount {
  name: string;
  slug: string;
  amount: number;
  code?: string;
}

export interface NextRecompete {
  end: string;
  amount: number;
  description: string;
  agency: string;
  days: number | null;
}

export interface Contractor {
  slug: string;
  name: string;
  uei: string;
  recipient_id: string;
  parent_name: string;
  location: { line: string; city: string; state: string; zip: string; country: string };
  business_types: string[];
  small_business: boolean;
  total_obligations: number;
  profiled: boolean;
  naics: { code: string; name: string; amount: number }[];
  agencies: { name: string; slug: string; amount: number }[];
  awards: Award[];
  usaspending_url: string;
  next_recompete: NextRecompete | null;
}

export interface ContractorRef {
  name: string;
  slug: string;
  uei: string;
  recipient_id: string;
  amount: number;
  usaspending_url: string;
}

export interface Agency {
  slug: string;
  name: string;
  code: string;
  amount: number;
  contractors: ContractorRef[];
  usaspending_url: string;
}

export interface NaicsPage {
  code: string;
  name: string;
  sector_code: string;
  sector_name: string;
  amount: number;
  contractors: ContractorRef[];
}

export interface Recompete {
  award_id: string;
  generated_id: string;
  slug: string;
  incumbent: string;
  uei: string;
  description: string;
  amount: number;
  agency: string;
  agency_slug: string;
  subagency: string;
  naics: string;
  naics_name: string;
  start: string;
  end: string;
  potential_end: string;
  days: number;
  type: string;
  set_aside: string;
  extent_competed: string;
  psc: string;
  usaspending_url: string;
}

export interface Opportunity {
  id: string;
  title: string;
  solicitation: string;
  agency: string;
  office: string;
  type: string;
  posted: string;
  posted_at: string;
  deadline: string;
  deadline_at: string;
  set_aside: string;
  set_aside_bucket: string;
  naics: string;
  state: string;
  city: string;
  contact_name: string;
  contact_email: string;
  link: string;
  description: string;
}

export interface SlimContractor {
  slug: string;
  name: string;
  uei: string;
  recipient_id: string;
  state: string;
  amount: number;
  profiled: boolean;
  small_business: boolean;
  top_naics: string;
  top_naics_code: string;
  top_agency: string;
  usaspending_url: string;
}

export interface Meta {
  generated_at: string;
  labels: {
    obligations_window: string;
    awards_since: string;
    recompete_horizon: string;
    recompete_horizon_days: number;
    recompete_min: number;
    past_days: number;
  };
  methodology: Record<string, string>;
  sources: {
    usaspending: SourceStatus;
    sam: SourceStatus;
  };
}

export interface SourceStatus {
  ok: boolean;
  fetched_at: string;
  error: string | null;
  kept_previous: boolean;
  contractors?: number;
  searchable?: number;
  recompetes?: number;
  notices?: number;
  extract_modified?: string | null;
  failures?: number;
}

export interface Placement {
  name: string;
  url: string;
  blurb: string;
  tier?: "claimed" | "featured" | "sponsor";
  logo?: string;
}

export interface SponsorsFile {
  profiles: Record<string, Placement>;
  radar: Placement | null;
  agencies: Record<string, Placement>;
  naics: Record<string, Placement>;
}
