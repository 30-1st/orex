import httpx
import re

SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt=2000-01-01&enddt=2026-12-31&forms=10-K,10-Q,8-K,DEF+14A,S-1"
SEC_COMPANY_URL = "https://efts.sec.gov/LATEST/search-index?q={query}&forms=10-K"
SEC_FULLTEXT_URL = "https://efts.sec.gov/LATEST/search-index?q=%22{query}%22"
SEC_EDGAR_COMPANY = "https://www.sec.gov/cgi-bin/browse-edgar?company={query}&CIK=&type=&dateb=&owner=include&count=20&search_text=&action=getcompany"

# SEC EDGAR full-text search API (free, no key needed)
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_COMPANY_SEARCH = "https://www.sec.gov/cgi-bin/browse-edgar"

# Use the proper EDGAR full-text search API
EDGAR_FTS_API = "https://efts.sec.gov/LATEST/search-index"
EDGAR_COMPANY_API = "https://efts.sec.gov/LATEST/search-index"

# Actually use the correct, working EDGAR API
EDGAR_API = "https://efts.sec.gov/LATEST/search-index"

# The real working endpoint
SEARCH_API = "https://efts.sec.gov/LATEST/search-index"

# OK let's just use what actually works - the EDGAR full text search
BASE = "https://efts.sec.gov/LATEST/search-index"


def search_sec(query: str) -> dict:
    """Search SEC EDGAR for filings mentioning a person or company."""

    clean = re.sub(r"[^a-zA-Z0-9 .'-]", "", query.strip())
    if not clean:
        return {"error": "Invalid query", "results": []}

    try:
        # Use EDGAR full-text search API
        resp = httpx.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q": f'"{clean}"',
                "forms": "10-K,10-Q,8-K,DEF 14A,S-1,4,3",
                "dateRange": "custom",
                "startdt": "2015-01-01",
                "enddt": "2026-12-31",
            },
            headers={"User-Agent": "Orex.ai research@orex.ai"},
            timeout=30,
        )

        # If that endpoint doesn't work, fall back to company search
        if resp.status_code != 200:
            return _company_search(clean)

        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])

        results = []
        for hit in hits[:15]:
            source = hit.get("_source", {})
            results.append({
                "filing_type": source.get("forms", ""),
                "entity": source.get("entity_name", ""),
                "filed_date": source.get("file_date", ""),
                "description": source.get("display_names", [""])[0] if source.get("display_names") else "",
                "url": f"https://www.sec.gov/Archives/edgar/data/{source.get('entity_id', '')}/{source.get('file_num', '')}" if source.get("entity_id") else "",
            })

        return {
            "query": clean,
            "total_results": data.get("hits", {}).get("total", {}).get("value", 0),
            "results": results,
            "source": "SEC EDGAR"
        }

    except Exception as e:
        return _company_search(clean)


def _company_search(query: str) -> dict:
    """Fallback: search EDGAR company database."""
    try:
        resp = httpx.get(
            "https://www.sec.gov/cgi-bin/browse-edgar",
            params={
                "company": query,
                "CIK": "",
                "type": "",
                "dateb": "",
                "owner": "include",
                "count": "20",
                "search_text": "",
                "action": "getcompany",
                "output": "atom",
            },
            headers={"User-Agent": "Orex.ai research@orex.ai"},
            timeout=30,
        )

        if resp.status_code != 200:
            return {"query": query, "results": [], "note": "SEC EDGAR unavailable"}

        # Parse atom feed for company entries
        text = resp.text
        entries = re.findall(
            r"<entry>.*?<title.*?>(.*?)</title>.*?<link.*?href=\"(.*?)\".*?</entry>",
            text,
            re.DOTALL
        )

        results = []
        for title, link in entries[:15]:
            results.append({
                "entity": title.strip(),
                "url": link.strip(),
                "source": "SEC EDGAR Company Search"
            })

        return {
            "query": query,
            "total_results": len(results),
            "results": results,
            "source": "SEC EDGAR"
        }

    except Exception as e:
        return {"query": query, "results": [], "error": str(e)}
