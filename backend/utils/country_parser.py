"""
country_parser.py

Supported TinyFish proxy countries (from https://docs.tinyfish.ai/key-concepts/proxies):
  US, GB, CA, DE, FR, JP, AU

If the user mentions a country NOT in this list, returns a special
{"unsupported": True, "country_name": "..."} dict so the caller can
show a helpful message instead of silently running all 7.

If no country is mentioned at all → returns ALL_COUNTRIES (default: all 7).
"""

import re

ALL_COUNTRIES = [
    {"code": "US", "flag": "🇺🇸", "name": "United States"},
    {"code": "GB", "flag": "🇬🇧", "name": "United Kingdom"},
    {"code": "DE", "flag": "🇩🇪", "name": "Germany"},
    {"code": "FR", "flag": "🇫🇷", "name": "France"},
    {"code": "JP", "flag": "🇯🇵", "name": "Japan"},
    {"code": "AU", "flag": "🇦🇺", "name": "Australia"},
    {"code": "CA", "flag": "🇨🇦", "name": "Canada"},
]

# Supported aliases → ISO code
_SUPPORTED: dict[str, str] = {
    # United States
    "us":"US","usa":"US","united states":"US","america":"US","american":"US","u.s.":"US",
    # United Kingdom
    "gb":"GB","uk":"GB","united kingdom":"GB","britain":"GB","great britain":"GB",
    "england":"GB","british":"GB",
    # Germany
    "de":"DE","germany":"DE","german":"DE","deutschland":"DE",
    # France
    "fr":"FR","france":"FR","french":"FR",
    # Japan
    "jp":"JP","japan":"JP","japanese":"JP",
    # Australia
    "au":"AU","australia":"AU","australian":"AU","oz":"AU",
    # Canada
    "ca":"CA","canada":"CA","canadian":"CA",
    # Regions → expand
    "europe":"DE,FR,GB","european":"DE,FR,GB","eu":"DE,FR,GB",
    "asia":"JP,AU","apac":"JP,AU",
    "north america":"US,CA","americas":"US,CA",
}

# Unsupported country names the user might type — mapped to display name
# so we can give a friendly "not supported" message
_UNSUPPORTED: dict[str, str] = {
    "india":"India","indian":"India","in":"India",
    "china":"China","chinese":"China","cn":"China",
    "brazil":"Brazil","brazilian":"Brazil","br":"Brazil",
    "russia":"Russia","russian":"Russia","ru":"Russia",
    "south korea":"South Korea","korea":"South Korea","korean":"South Korea","kr":"South Korea",
    "mexico":"Mexico","mexican":"Mexico","mx":"Mexico",
    "italy":"Italy","italian":"Italy","it":"Italy",
    "spain":"Spain","spanish":"Spain","es":"Spain",
    "netherlands":"Netherlands","dutch":"Netherlands","nl":"Netherlands",
    "singapore":"Singapore","sg":"Singapore",
    "indonesia":"Indonesia","id":"Indonesia",
    "turkey":"Turkey","turkish":"Turkey","tr":"Turkey",
    "saudi arabia":"Saudi Arabia","saudi":"Saudi Arabia","ksa":"Saudi Arabia",
    "uae":"UAE","dubai":"UAE","emirates":"UAE",
    "new zealand":"New Zealand","nz":"New Zealand",
    "argentina":"Argentina","ar":"Argentina",
    "colombia":"Colombia","co":"Colombia",
    "egypt":"Egypt","eg":"Egypt",
    "pakistan":"Pakistan","pk":"Pakistan",
    "bangladesh":"Bangladesh","bd":"Bangladesh",
    "nigeria":"Nigeria","ng":"Nigeria",
    "kenya":"Kenya","ke":"Kenya",
    "south africa":"South Africa","za":"South Africa",
    "sweden":"Sweden","swedish":"Sweden","se":"Sweden",
    "norway":"Norway","norwegian":"Norway","no":"Norway",
    "denmark":"Denmark","danish":"Denmark","dk":"Denmark",
    "finland":"Finland","finnish":"Finland","fi":"Finland",
    "poland":"Poland","polish":"Poland","pl":"Poland",
    "austria":"Austria","at":"Austria",
    "switzerland":"Switzerland","swiss":"Switzerland","ch":"Switzerland",
    "belgium":"Belgium","belgian":"Belgium","be":"Belgium",
    "portugal":"Portugal","portuguese":"Portugal","pt":"Portugal",
    "greece":"Greece","greek":"Greece","gr":"Greece",
    "czech republic":"Czech Republic","czechia":"Czech Republic","cz":"Czech Republic",
    "hungary":"Hungary","hu":"Hungary",
    "romania":"Romania","ro":"Romania",
    "thailand":"Thailand","thai":"Thailand","th":"Thailand",
    "vietnam":"Vietnam","vietnamese":"Vietnam","vn":"Vietnam",
    "philippines":"Philippines","filipino":"Philippines","ph":"Philippines",
    "malaysia":"Malaysia","my":"Malaysia",
    "taiwan":"Taiwan","tw":"Taiwan",
    "hong kong":"Hong Kong","hk":"Hong Kong",
    "israel":"Israel","il":"Israel",
    "ukraine":"Ukraine","ua":"Ukraine",
    "iran":"Iran","ir":"Iran",
    "iraq":"Iraq","iq":"Iraq",
}

_CODE_TO_COUNTRY = {c["code"]: c for c in ALL_COUNTRIES}

# Pre-compile patterns sorted longest-first
def _compile(d: dict[str, str]) -> list[tuple[re.Pattern, str]]:
    result = []
    for alias, val in sorted(d.items(), key=lambda kv: len(kv[0]), reverse=True):
        if len(alias) <= 3:
            pat = re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
        else:
            pat = re.compile(re.escape(alias), re.IGNORECASE)
        result.append((pat, val))
    return result

_SUPPORTED_PATTERNS   = _compile(_SUPPORTED)
_UNSUPPORTED_PATTERNS = _compile(_UNSUPPORTED)

SUPPORTED_LIST = "🇺🇸 US · 🇬🇧 UK · 🇩🇪 Germany · 🇫🇷 France · 🇯🇵 Japan · 🇦🇺 Australia · 🇨🇦 Canada"


def parse_countries(message: str) -> list[dict] | dict:
    """
    Returns:
      - list of country dicts  → run these countries
      - {"unsupported": True, "country_name": "X"}  → country not supported
      - ALL_COUNTRIES  → no specific country mentioned, run all 7
    """
    # Check unsupported first (before supported, to catch e.g. "india" before "in" matches "india")
    for pat, display_name in _UNSUPPORTED_PATTERNS:
        if pat.search(message):
            return {"unsupported": True, "country_name": display_name}

    found_codes: set[str] = set()
    for pat, codes in _SUPPORTED_PATTERNS:
        if pat.search(message):
            for code in codes.split(","):
                found_codes.add(code.strip())

    if not found_codes:
        return ALL_COUNTRIES

    return [c for c in ALL_COUNTRIES if c["code"] in found_codes]