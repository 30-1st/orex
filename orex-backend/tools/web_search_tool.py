import re
import httpx
from urllib.parse import unquote

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def web_search(query: str) -> dict:
    """
    Search the web via DuckDuckGo for current information.
    Returns titles, snippets, and URLs from top results.
    Use for: who is [person], what is [thing], current events, 
    any question the model's training data can't answer.
    """

    clean = query.strip()
    if not clean or len(clean) > 500:
        return {"error": "Invalid query"}

    results = {
        "query": clean,
        "results": [],
    }

    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": clean},
            headers=HEADERS,
            timeout=15,
            follow_redirects=True,
        )

        if resp.status_code != 200:
            return {"query": clean, "results": [], "error": f"Search returned {resp.status_code}"}

        html = resp.text

        # Extract results with titles, URLs, and snippets
        matches = re.findall(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:td|div|span)',
            html,
            re.DOTALL,
        )

        for url, title, snippet in matches[:8]:
            # Clean DDG redirect URLs
            if "uddg=" in url:
                m = re.search(r"uddg=([^&]+)", url)
                if m:
                    url = unquote(m.group(1))

            # Strip HTML tags
            title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()

            if title and snippet:
                results["results"].append({
                    "title": title[:300],
                    "snippet": snippet[:500],
                    "url": url,
                })

        results["total"] = len(results["results"])

    except Exception as e:
        results["error"] = str(e)

    # Also try DuckDuckGo instant answer API for quick facts
    try:
        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={
                "q": clean,
                "format": "json",
                "no_redirect": "1",
                "skip_disambig": "1",
            },
            headers={"User-Agent": "Orex.ai"},
            timeout=10,
        )

        if resp.status_code == 200:
            data = resp.json()

            # Abstract text (Wikipedia-style summary)
            abstract = data.get("AbstractText", "")
            if abstract:
                results["instant_answer"] = {
                    "text": abstract[:1000],
                    "source": data.get("AbstractSource", ""),
                    "url": data.get("AbstractURL", ""),
                }

            # Infobox data
            infobox = data.get("Infobox", {})
            if infobox and infobox.get("content"):
                facts = {}
                for item in infobox["content"][:10]:
                    label = item.get("label", "")
                    value = item.get("value", "")
                    if label and value:
                        facts[label] = str(value)[:200]
                if facts:
                    results["infobox"] = facts

            # Related topics
            related = data.get("RelatedTopics", [])
            if related:
                related_items = []
                for topic in related[:5]:
                    text = topic.get("Text", "")
                    if text:
                        related_items.append(text[:200])
                if related_items:
                    results["related"] = related_items

    except Exception:
        pass

    return results
