import httpx
import re


# State Secretary of State / business registry endpoints
STATE_REGISTRIES = {
    "NJ": {
        "name": "NJ Division of Revenue - Business Gateway",
        "url": "https://www.njportal.com/DOR/BusinessNameSearch",
        "api_url": None,
        "note": "NJ business name search"
    },
    "NY": {
        "name": "NY Department of State - Corporation & Business Entity Database",
        "url": "https://apps.dos.ny.gov/publicInquiry/",
        "api_url": None,
        "note": "NY DOS entity search"
    },
    "FL": {
        "name": "Florida Division of Corporations - Sunbiz",
        "url": "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
        "api_url": None,
        "note": "FL Sunbiz — one of the best state business registries"
    },
    "PA": {
        "name": "PA Department of State - Business Entity Search",
        "url": "https://www.corporations.pa.gov/search/corpsearch",
        "api_url": None,
        "note": "PA corporation search"
    },
    "DE": {
        "name": "Delaware Division of Corporations",
        "url": "https://icis.corp.delaware.gov/ecorp/entitysearch/namesearch.aspx",
        "api_url": None,
        "note": "DE — where most US corps are registered"
    },
    "MA": {
        "name": "Massachusetts Secretary of the Commonwealth",
        "url": "https://corp.sec.state.ma.us/corpweb/CorpSearch/CorpSearch.aspx",
        "api_url": None,
        "note": "MA corporation search"
    },
    "CT": {
        "name": "Connecticut CONCORD Business Search",
        "url": "https://service.ct.gov/business/s/onlinebusinesssearch",
        "api_url": None,
        "note": "CT business search"
    },
    "MD": {
        "name": "Maryland SDAT Business Search",
        "url": "https://egov.maryland.gov/BusinessExpress/EntitySearch",
        "api_url": None,
        "note": "MD business entity search"
    },
    "VA": {
        "name": "Virginia SCC Clerk's Information System",
        "url": "https://cis.scc.virginia.gov/EntitySearch/Index",
        "api_url": None,
        "note": "VA SCC entity search"
    },
    "GA": {
        "name": "Georgia Secretary of State - Corporations Division",
        "url": "https://ecorp.sos.ga.gov/BusinessSearch",
        "api_url": None,
        "note": "GA business search"
    },
    "NC": {
        "name": "North Carolina Secretary of State",
        "url": "https://www.sosnc.gov/online_services/search/by_title/_Business_Registration",
        "api_url": None,
        "note": "NC business registration search"
    },
    "SC": {
        "name": "South Carolina Secretary of State",
        "url": "https://businessfilings.sc.gov/businessfiling/Entity/Search",
        "api_url": None,
        "note": "SC business filing search"
    },
    "DC": {
        "name": "DC CorpOnline",
        "url": "https://corponline.dcra.dc.gov/Home.aspx",
        "api_url": None,
        "note": "DC business entity search"
    },
}


def search_business_entity(query: str, state: str) -> dict:
    """
    Search state business registries for entities matching a query.

    Most state SOS sites require browser interaction (JS, sessions).
    This provides direct search links and attempts automated search where possible.
    """

    state = state.upper().strip()
    clean = re.sub(r"[^a-zA-Z0-9 .'\-&]", "", query.strip())

    if not clean:
        return {"error": "Invalid query"}

    if state not in STATE_REGISTRIES:
        return {
            "error": f"State {state} not yet supported",
            "supported_states": list(STATE_REGISTRIES.keys()),
        }

    registry = STATE_REGISTRIES[state]

    result = {
        "query": clean,
        "state": state,
        "registry": registry["name"],
        "search_links": [
            {
                "source": registry["name"],
                "url": registry["url"],
                "instruction": f"Search for: {clean}",
            }
        ],
        "automated_results": [],
        "note": registry["note"],
    }

    # OpenCorporates as a fallback — free API, covers all US states
    oc_results = _search_opencorporates(clean, state)
    if oc_results:
        result["automated_results"] = oc_results

    return result


def _search_opencorporates(query: str, state: str) -> list:
    """Search OpenCorporates free API."""

    state_map = {
        "NJ": "us_nj", "NY": "us_ny", "FL": "us_fl", "PA": "us_pa",
        "DE": "us_de", "MA": "us_ma", "CT": "us_ct", "MD": "us_md",
        "VA": "us_va", "GA": "us_ga", "NC": "us_nc", "SC": "us_sc",
        "DC": "us_dc",
    }

    jurisdiction = state_map.get(state, f"us_{state.lower()}")

    try:
        resp = httpx.get(
            "https://api.opencorporates.com/v0.4/companies/search",
            params={
                "q": query,
                "jurisdiction_code": jurisdiction,
                "per_page": 15,
            },
            headers={"User-Agent": "Orex.ai research@orex.ai"},
            timeout=20,
        )

        if resp.status_code != 200:
            return []

        data = resp.json()
        companies = data.get("results", {}).get("companies", [])

        return [
            {
                "name": c["company"]["name"],
                "company_number": c["company"].get("company_number", ""),
                "status": c["company"].get("current_status", ""),
                "incorporation_date": c["company"].get("incorporation_date", ""),
                "registered_address": c["company"].get("registered_address_in_full", ""),
                "url": c["company"].get("opencorporates_url", ""),
                "source": c["company"].get("source", {}).get("url", ""),
            }
            for c in companies
        ]

    except Exception:
        return []


def _search_pacer_parties(query: str) -> list:
    """
    PACER party search — requires PACER credentials.
    Placeholder for when credentials are configured.
    """
    return []
