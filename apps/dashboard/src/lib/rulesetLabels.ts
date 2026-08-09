/**
 * Human-readable names for the ruleset codes on disk.
 *
 * A lookup, not a source of truth. Anything missing falls back to the raw
 * code, so adding a ruleset YAML makes it selectable immediately without a
 * frontend change — the server decides what exists, this only decides how it
 * reads. Shared by signup and workspace settings so the two can never
 * disagree about what "us-ca" means.
 */

export const INDUSTRY_LABEL: Record<string, string> = {
  healthcare_ndis: "NDIS / disability services",
  aged_care: "Aged care",
  bookkeeping: "Bookkeeping & payroll",
  data_privacy: "Data privacy & protection",
  contract_review: "Contract review",
};

export const JURISDICTION_LABEL: Record<string, string> = {
  au: "Australia",
  in: "India",
  eu: "European Union",
  uk: "United Kingdom",
  "us-ca": "United States (California)",
  ca: "Canada",
  sg: "Singapore",
  br: "Brazil",
  cn: "China",
  ae: "United Arab Emirates",
  za: "South Africa",
  generic: "Any jurisdiction",
};

/** Case-insensitive: tenants created before the picker stored "AU", not "au". */
export const label = (map: Record<string, string>, key: string): string =>
  map[key?.toLowerCase()] ?? key;
