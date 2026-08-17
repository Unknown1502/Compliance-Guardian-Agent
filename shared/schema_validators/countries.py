"""ISO 3166-1 country registry and the jurisdiction resolver built on it.

Country and jurisdiction are deliberately different concepts, kept in two
different places on purpose:

  Country       A fact about where a business operates. This list is
                complete and does not change based on what ComplianceGuardian
                can currently check — Afghanistan is a country whether or not
                a ruleset exists for it.
  Jurisdiction  Which ruleset file the compliance engine actually loads
                (rulesets/<industry>/<jurisdiction>.yaml). Only ever as
                complete as that directory.

This module is the ONE place that maps a country to a jurisdiction, so that
mapping can never drift into being duplicated — or silently guessed — in
signup, the compliance engine, or a report. A country with no entry in
COUNTRY_TO_JURISDICTION is not an error in this file; resolve_jurisdiction()
returning None for it is the correct, honest answer, and callers are the ones
responsible for turning that into a clear "not supported yet" instead of
substituting a different jurisdiction.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Country:
    alpha2: str
    alpha3: str
    name: str


# Full ISO 3166-1 list of officially assigned country codes (UN member and
# observer states plus other ISO-assigned territories). Alphabetical by name.
COUNTRIES: tuple[Country, ...] = (
    Country("AF", "AFG", "Afghanistan"),
    Country("AL", "ALB", "Albania"),
    Country("DZ", "DZA", "Algeria"),
    Country("AD", "AND", "Andorra"),
    Country("AO", "AGO", "Angola"),
    Country("AG", "ATG", "Antigua and Barbuda"),
    Country("AR", "ARG", "Argentina"),
    Country("AM", "ARM", "Armenia"),
    Country("AU", "AUS", "Australia"),
    Country("AT", "AUT", "Austria"),
    Country("AZ", "AZE", "Azerbaijan"),
    Country("BS", "BHS", "Bahamas"),
    Country("BH", "BHR", "Bahrain"),
    Country("BD", "BGD", "Bangladesh"),
    Country("BB", "BRB", "Barbados"),
    Country("BY", "BLR", "Belarus"),
    Country("BE", "BEL", "Belgium"),
    Country("BZ", "BLZ", "Belize"),
    Country("BJ", "BEN", "Benin"),
    Country("BT", "BTN", "Bhutan"),
    Country("BO", "BOL", "Bolivia"),
    Country("BA", "BIH", "Bosnia and Herzegovina"),
    Country("BW", "BWA", "Botswana"),
    Country("BR", "BRA", "Brazil"),
    Country("BN", "BRN", "Brunei"),
    Country("BG", "BGR", "Bulgaria"),
    Country("BF", "BFA", "Burkina Faso"),
    Country("BI", "BDI", "Burundi"),
    Country("CV", "CPV", "Cabo Verde"),
    Country("KH", "KHM", "Cambodia"),
    Country("CM", "CMR", "Cameroon"),
    Country("CA", "CAN", "Canada"),
    Country("CF", "CAF", "Central African Republic"),
    Country("TD", "TCD", "Chad"),
    Country("CL", "CHL", "Chile"),
    Country("CN", "CHN", "China"),
    Country("CO", "COL", "Colombia"),
    Country("KM", "COM", "Comoros"),
    Country("CG", "COG", "Congo"),
    Country("CD", "COD", "Congo (DRC)"),
    Country("CR", "CRI", "Costa Rica"),
    Country("CI", "CIV", "Côte d'Ivoire"),
    Country("HR", "HRV", "Croatia"),
    Country("CU", "CUB", "Cuba"),
    Country("CY", "CYP", "Cyprus"),
    Country("CZ", "CZE", "Czechia"),
    Country("DK", "DNK", "Denmark"),
    Country("DJ", "DJI", "Djibouti"),
    Country("DM", "DMA", "Dominica"),
    Country("DO", "DOM", "Dominican Republic"),
    Country("EC", "ECU", "Ecuador"),
    Country("EG", "EGY", "Egypt"),
    Country("SV", "SLV", "El Salvador"),
    Country("GQ", "GNQ", "Equatorial Guinea"),
    Country("ER", "ERI", "Eritrea"),
    Country("EE", "EST", "Estonia"),
    Country("SZ", "SWZ", "Eswatini"),
    Country("ET", "ETH", "Ethiopia"),
    Country("FJ", "FJI", "Fiji"),
    Country("FI", "FIN", "Finland"),
    Country("FR", "FRA", "France"),
    Country("GA", "GAB", "Gabon"),
    Country("GM", "GMB", "Gambia"),
    Country("GE", "GEO", "Georgia"),
    Country("DE", "DEU", "Germany"),
    Country("GH", "GHA", "Ghana"),
    Country("GR", "GRC", "Greece"),
    Country("GD", "GRD", "Grenada"),
    Country("GT", "GTM", "Guatemala"),
    Country("GN", "GIN", "Guinea"),
    Country("GW", "GNB", "Guinea-Bissau"),
    Country("GY", "GUY", "Guyana"),
    Country("HT", "HTI", "Haiti"),
    Country("HN", "HND", "Honduras"),
    Country("HK", "HKG", "Hong Kong"),
    Country("HU", "HUN", "Hungary"),
    Country("IS", "ISL", "Iceland"),
    Country("IN", "IND", "India"),
    Country("ID", "IDN", "Indonesia"),
    Country("IR", "IRN", "Iran"),
    Country("IQ", "IRQ", "Iraq"),
    Country("IE", "IRL", "Ireland"),
    Country("IL", "ISR", "Israel"),
    Country("IT", "ITA", "Italy"),
    Country("JM", "JAM", "Jamaica"),
    Country("JP", "JPN", "Japan"),
    Country("JO", "JOR", "Jordan"),
    Country("KZ", "KAZ", "Kazakhstan"),
    Country("KE", "KEN", "Kenya"),
    Country("KI", "KIR", "Kiribati"),
    Country("KP", "PRK", "Korea (North)"),
    Country("KR", "KOR", "Korea (South)"),
    Country("KW", "KWT", "Kuwait"),
    Country("KG", "KGZ", "Kyrgyzstan"),
    Country("LA", "LAO", "Laos"),
    Country("LV", "LVA", "Latvia"),
    Country("LB", "LBN", "Lebanon"),
    Country("LS", "LSO", "Lesotho"),
    Country("LR", "LBR", "Liberia"),
    Country("LY", "LBY", "Libya"),
    Country("LI", "LIE", "Liechtenstein"),
    Country("LT", "LTU", "Lithuania"),
    Country("LU", "LUX", "Luxembourg"),
    Country("MO", "MAC", "Macao"),
    Country("MG", "MDG", "Madagascar"),
    Country("MW", "MWI", "Malawi"),
    Country("MY", "MYS", "Malaysia"),
    Country("MV", "MDV", "Maldives"),
    Country("ML", "MLI", "Mali"),
    Country("MT", "MLT", "Malta"),
    Country("MH", "MHL", "Marshall Islands"),
    Country("MR", "MRT", "Mauritania"),
    Country("MU", "MUS", "Mauritius"),
    Country("MX", "MEX", "Mexico"),
    Country("FM", "FSM", "Micronesia"),
    Country("MD", "MDA", "Moldova"),
    Country("MC", "MCO", "Monaco"),
    Country("MN", "MNG", "Mongolia"),
    Country("ME", "MNE", "Montenegro"),
    Country("MA", "MAR", "Morocco"),
    Country("MZ", "MOZ", "Mozambique"),
    Country("MM", "MMR", "Myanmar"),
    Country("NA", "NAM", "Namibia"),
    Country("NR", "NRU", "Nauru"),
    Country("NP", "NPL", "Nepal"),
    Country("NL", "NLD", "Netherlands"),
    Country("NZ", "NZL", "New Zealand"),
    Country("NI", "NIC", "Nicaragua"),
    Country("NE", "NER", "Niger"),
    Country("NG", "NGA", "Nigeria"),
    Country("MK", "MKD", "North Macedonia"),
    Country("NO", "NOR", "Norway"),
    Country("OM", "OMN", "Oman"),
    Country("PK", "PAK", "Pakistan"),
    Country("PW", "PLW", "Palau"),
    Country("PS", "PSE", "Palestine"),
    Country("PA", "PAN", "Panama"),
    Country("PG", "PNG", "Papua New Guinea"),
    Country("PY", "PRY", "Paraguay"),
    Country("PE", "PER", "Peru"),
    Country("PH", "PHL", "Philippines"),
    Country("PL", "POL", "Poland"),
    Country("PT", "PRT", "Portugal"),
    Country("QA", "QAT", "Qatar"),
    Country("RO", "ROU", "Romania"),
    Country("RU", "RUS", "Russia"),
    Country("RW", "RWA", "Rwanda"),
    Country("KN", "KNA", "Saint Kitts and Nevis"),
    Country("LC", "LCA", "Saint Lucia"),
    Country("VC", "VCT", "Saint Vincent and the Grenadines"),
    Country("WS", "WSM", "Samoa"),
    Country("SM", "SMR", "San Marino"),
    Country("ST", "STP", "Sao Tome and Principe"),
    Country("SA", "SAU", "Saudi Arabia"),
    Country("SN", "SEN", "Senegal"),
    Country("RS", "SRB", "Serbia"),
    Country("SC", "SYC", "Seychelles"),
    Country("SL", "SLE", "Sierra Leone"),
    Country("SG", "SGP", "Singapore"),
    Country("SK", "SVK", "Slovakia"),
    Country("SI", "SVN", "Slovenia"),
    Country("SB", "SLB", "Solomon Islands"),
    Country("SO", "SOM", "Somalia"),
    Country("ZA", "ZAF", "South Africa"),
    Country("SS", "SSD", "South Sudan"),
    Country("ES", "ESP", "Spain"),
    Country("LK", "LKA", "Sri Lanka"),
    Country("SD", "SDN", "Sudan"),
    Country("SR", "SUR", "Suriname"),
    Country("SE", "SWE", "Sweden"),
    Country("CH", "CHE", "Switzerland"),
    Country("SY", "SYR", "Syria"),
    Country("TW", "TWN", "Taiwan"),
    Country("TJ", "TJK", "Tajikistan"),
    Country("TZ", "TZA", "Tanzania"),
    Country("TH", "THA", "Thailand"),
    Country("TL", "TLS", "Timor-Leste"),
    Country("TG", "TGO", "Togo"),
    Country("TO", "TON", "Tonga"),
    Country("TT", "TTO", "Trinidad and Tobago"),
    Country("TN", "TUN", "Tunisia"),
    Country("TR", "TUR", "Türkiye"),
    Country("TM", "TKM", "Turkmenistan"),
    Country("TV", "TUV", "Tuvalu"),
    Country("UG", "UGA", "Uganda"),
    Country("UA", "UKR", "Ukraine"),
    Country("AE", "ARE", "United Arab Emirates"),
    Country("GB", "GBR", "United Kingdom"),
    Country("US", "USA", "United States"),
    Country("UY", "URY", "Uruguay"),
    Country("UZ", "UZB", "Uzbekistan"),
    Country("VU", "VUT", "Vanuatu"),
    Country("VA", "VAT", "Vatican City"),
    Country("VE", "VEN", "Venezuela"),
    Country("VN", "VNM", "Vietnam"),
    Country("YE", "YEM", "Yemen"),
    Country("ZM", "ZMB", "Zambia"),
    Country("ZW", "ZWE", "Zimbabwe"),
)

COUNTRY_BY_ALPHA2: dict[str, Country] = {c.alpha2: c for c in COUNTRIES}


def is_valid_country_code(code: str) -> bool:
    return code.upper() in COUNTRY_BY_ALPHA2


def country_name(code: str) -> str:
    """The ISO name for a code, or the code itself if it isn't recognized —
    a raw code is a more honest fallback than a fabricated name."""
    c = COUNTRY_BY_ALPHA2.get(code.upper())
    return c.name if c else code


# --- Country -> ruleset jurisdiction resolution -----------------------------
#
# EU member states all resolve to "eu": the existing data_privacy/eu.yaml
# ruleset is modeled on the GDPR, which is EU-wide by construction, so there
# was never going to be a separate ruleset per member state for the one
# regulation that is explicitly harmonized across all of them.
_EU_MEMBERS: frozenset[str] = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
})

# Direct country -> jurisdiction-code mappings, one per ruleset file that
# actually exists under rulesets/*/*.yaml today. Every country NOT listed
# here (and not an EU member) has no automatic mapping — that is correct,
# not a gap to silently paper over.
_DIRECT: dict[str, str] = {
    "AU": "au",
    "IN": "in",
    # Ruleset file is uk.yaml — the historical jurisdiction code predates
    # this registry and does not match the ISO alpha-2 (GB) for this one
    # country. Renaming the ruleset file is a separate, larger change; this
    # mapping is the translation layer so the ISO list never has to change.
    "GB": "uk",
    "CA": "ca",
    "SG": "sg",
    "BR": "br",
    "CN": "cn",
    "AE": "ae",
    "ZA": "za",
}

COUNTRY_TO_JURISDICTION: dict[str, str] = {
    **{code: "eu" for code in _EU_MEMBERS},
    **_DIRECT,  # direct mappings take precedence in the (currently empty)
                # event a country appears in both.
}


def resolve_jurisdiction(country_code: str) -> str | None:
    """The ruleset jurisdiction code for a country, or None if unmapped.

    None is not an error condition — it means no ruleset has been authored
    for that country yet. The caller's job is to turn that into an honest
    "not supported yet" response, never to substitute a different
    jurisdiction in its place.
    """
    return COUNTRY_TO_JURISDICTION.get(country_code.upper())
