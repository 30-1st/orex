import httpx
import re
from urllib.parse import quote


# State court search endpoints — these are the public-facing search portals
# Each state has a different system so each needs its own implementation
STATE_COURTS = {
    "NJ": {
        "name": "New Jersey Courts",
        "search_url": "https://portal.njcourts.gov/webe8/CivilCaseJacketWeb/pages/civilCaseSearch.faces",
        "manual_url": "https://portal.njcourts.gov/webe8/CivilCaseJacketWeb/pages/civilCaseSearch.faces",
        "note": "NJ civil case search — requires manual browser interaction for full results"
    },
    "NY": {
        "name": "New York eCourts (WebCivil Supreme)",
        "search_url": "https://iapps.courts.state.ny.us/nyscef/CaseSearch",
        "manual_url": "https://iapps.courts.state.ny.us/nyscef/CaseSearch?TAession=N",
        "note": "NY eCourts — NYSCEF case search"
    },
    "FL": {
        "name": "Florida Courts",
        "search_url": "https://www.flcourts.gov/Resources-Services/Court-Records",
        "manual_url": "https://www.myflcourtaccess.com/",
        "note": "FL varies by county — Miami-Dade, Broward, etc. have separate portals"
    },
    "PA": {
        "name": "Pennsylvania Unified Judicial System",
        "search_url": "https://ujsportal.pacourts.us/CaseSearch",
        "manual_url": "https://ujsportal.pacourts.us/CaseSearch",
        "note": "PA UJS portal — searchable by participant name"
    },
    "MA": {
        "name": "Massachusetts Trial Court",
        "search_url": "https://www.masscourts.org/ecourtpub/",
        "manual_url": "https://www.masscourts.org/ecourtpub/",
        "note": "MA Trial Court electronic case access"
    },
    "CT": {
        "name": "Connecticut Judicial Branch",
        "search_url": "https://www.jud2.ct.gov/crdockets/SearchByName.aspx",
        "manual_url": "https://www.jud2.ct.gov/crdockets/SearchByName.aspx",
        "note": "CT judicial case lookup"
    },
    "MD": {
        "name": "Maryland Judiciary Case Search",
        "search_url": "https://casesearch.courts.state.md.us/casesearch/",
        "manual_url": "https://casesearch.courts.state.md.us/casesearch/",
        "note": "MD case search — one of the best public court search systems"
    },
    "VA": {
        "name": "Virginia Courts",
        "search_url": "https://www.vacourts.gov/caseinfo/home.html",
        "manual_url": "https://www.vacourts.gov/caseinfo/home.html",
        "note": "VA court case information system"
    },
    "GA": {
        "name": "Georgia Courts",
        "search_url": "https://www.georgiacourts.gov/",
        "manual_url": "https://www.georgiacourts.gov/",
        "note": "GA — varies by county, no statewide unified search"
    },
    "NC": {
        "name": "North Carolina Courts",
        "search_url": "https://www.nccourts.gov/court-dates",
        "manual_url": "https://www.nccourts.gov/court-dates",
        "note": "NC eCourts — recently modernized system"
    },
    "SC": {
        "name": "South Carolina Courts",
        "search_url": "https://www.sccourts.org/caseSearch/",
        "manual_url": "https://www.sccourts.org/caseSearch/",
        "note": "SC court case search"
    },
    "DC": {
        "name": "DC Superior Court",
        "search_url": "https://www.dccourts.gov/court-cases",
        "manual_url": "https://www.dccourts.gov/court-cases",
        "note": "DC Superior Court case search"
    },
}


def search_state_courts(name: str, state: str) -> dict:
    """
    Search state court records for a person.

    Most state court systems require browser-based interaction (CAPTCHAs, sessions, JS rendering).
    This tool provides direct links to search portals with pre-formatted queries,
    and attempts automated search where APIs exist.

    For PA specifically, UJS has a more accessible search system.
    """

    state = state.upper().strip()
    clean_name = re.sub(r"[^a-zA-Z '\-]", "", name.strip())

    if not clean_name:
        return {"error": "Invalid name"}

    if state not in STATE_COURTS:
        return {
            "error": f"State {state} not yet supported",
            "supported_states": list(STATE_COURTS.keys()),
        }

    court = STATE_COURTS[state]

    result = {
        "query_name": clean_name,
        "state": state,
        "court_system": court["name"],
        "search_links": [],
        "automated_results": [],
        "note": court["note"],
    }

    # Provide direct search links
    result["search_links"].append({
        "source": court["name"],
        "url": court["manual_url"],
        "instruction": f"Search for: {clean_name}"
    })

    # For PA, try automated search (UJS has a somewhat accessible API)
    if state == "PA":
        pa_results = _search_pa_ujs(clean_name)
        result["automated_results"] = pa_results

    # For MD, try automated search (MD has one of the best public systems)
    if state == "MD":
        md_results = _search_md_courts(clean_name)
        result["automated_results"] = md_results

    # Always add PACER link for federal cases
    result["search_links"].append({
        "source": "PACER (Federal Courts)",
        "url": "https://www.pacer.gov/",
        "instruction": f"Search PACER for federal cases involving: {clean_name}",
        "note": "PACER requires free registration. $0.10/page for documents."
    })

    return result


def _search_pa_ujs(name: str) -> list:
    """Try PA UJS search."""
    try:
        resp = httpx.get(
            "https://ujsportal.pacourts.us/Report/CpCourtCaseCountyReport",
            params={"SearchBy": "ParticipantName", "ParticipantName": name},
            headers={"User-Agent": "Orex.ai research@orex.ai"},
            timeout=20,
            follow_redirects=True,
        )
        if resp.status_code == 200 and "No Cases Found" not in resp.text:
            # PA returns HTML — extract case links
            cases = re.findall(
                r'href="(/Report/CpCourtCaseReport\?docketNumber=[^"]+)".*?>(.*?)</a>',
                resp.text
            )
            return [
                {
                    "docket": match[1].strip(),
                    "url": f"https://ujsportal.pacourts.us{match[0]}",
                }
                for match in cases[:20]
            ]
    except Exception:
        pass
    return []


def _search_md_courts(name: str) -> list:
    """Try Maryland case search."""
    try:
        resp = httpx.get(
            "https://casesearch.courts.state.md.us/casesearch/inquirySearch.jis",
            params={
                "lastName": name.split()[-1] if " " in name else name,
                "firstName": name.split()[0] if " " in name else "",
                "action": "Search",
            },
            headers={"User-Agent": "Orex.ai research@orex.ai"},
            timeout=20,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            cases = re.findall(
                r'href="(inquiryDetail\.jis\?[^"]+)".*?<td[^>]*>(.*?)</td>',
                resp.text,
                re.DOTALL,
            )
            return [
                {
                    "case": match[1].strip()[:100],
                    "url": f"https://casesearch.courts.state.md.us/casesearch/{match[0]}",
                }
                for match in cases[:20]
            ]
    except Exception:
        pass
    return []
