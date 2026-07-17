import re
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Google dork targets for social profiles
PLATFORM_DORKS = [
    ("LinkedIn", 'site:linkedin.com/in/ "{name}"'),
    ("Instagram", 'site:instagram.com "{name}"'),
    ("Facebook", 'site:facebook.com "{name}"'),
    ("Twitter/X", 'site:x.com "{name}"'),
    ("TikTok", 'site:tiktok.com "@" "{name}"'),
    ("GitHub", 'site:github.com "{name}"'),
    ("YouTube", 'site:youtube.com "{name}"'),
    ("Reddit", 'site:reddit.com/user "{name}"'),
    ("Medium", 'site:medium.com "@" "{name}"'),
    ("SoundCloud", 'site:soundcloud.com "{name}"'),
]


def search_name_to_handles(name: str, groq_api_key: str) -> dict:
    """
    Search for a real name across social platforms to find matching handles.
    Uses search engine queries to find public profiles matching the name.
    """

    clean = re.sub(r"[^a-zA-Z '\-.]", "", name.strip())
    if not clean or len(clean) < 2:
        return {"error": "Invalid name"}

    results = {
        "query_name": clean,
        "found_profiles": [],
        "search_links": [],
    }

    # Try DuckDuckGo HTML search (no API key needed, less aggressive blocking)
    for platform, dork_template in PLATFORM_DORKS:
        query = dork_template.replace("{name}", clean)
        profiles = _search_duckduckgo(query, platform)
        if profiles:
            results["found_profiles"].extend(profiles)
        else:
            # Provide manual search links as fallback
            results["search_links"].append({
                "platform": platform,
                "search_query": query,
                "manual_url": f"https://duckduckgo.com/?q={_url_encode(query)}",
            })

    # Deduplicate by URL
    seen = set()
    deduped = []
    for p in results["found_profiles"]:
        url = p.get("url", "").lower().rstrip("/")
        if url not in seen:
            seen.add(url)
            deduped.append(p)
    results["found_profiles"] = deduped

    # If we found profiles, try to use AI to pick the best matches
    if results["found_profiles"] and groq_api_key:
        results["found_profiles"] = _rank_with_ai(
            clean, results["found_profiles"], groq_api_key
        )

    results["total_found"] = len(results["found_profiles"])

    return results


def _url_encode(text: str) -> str:
    """Simple URL encoding."""
    return text.replace(" ", "+").replace('"', "%22").replace(":", "%3A").replace("/", "%2F")


def _search_duckduckgo(query: str, platform: str) -> list:
    """Search DuckDuckGo HTML version for results."""
    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=HEADERS,
            timeout=15,
            follow_redirects=True,
        )

        if resp.status_code != 200:
            return []

        html = resp.text
        results = []

        # Extract result links and titles
        # DDG HTML format: <a rel="nofollow" class="result__a" href="URL">Title</a>
        matches = re.findall(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        for url, title in matches[:3]:
            # Clean URL (DDG sometimes wraps URLs)
            if "uddg=" in url:
                m = re.search(r"uddg=([^&]+)", url)
                if m:
                    from urllib.parse import unquote
                    url = unquote(m.group(1))

            # Clean title
            title = re.sub(r"<[^>]+>", "", title).strip()

            # Only keep if it's actually a social profile URL
            if _is_profile_url(url):
                handle = _extract_handle(url)
                results.append({
                    "platform": platform,
                    "url": url,
                    "title": title[:200],
                    "handle": handle,
                })

        return results

    except Exception:
        return []


def _is_profile_url(url: str) -> bool:
    """Check if URL looks like a social media profile."""
    profile_patterns = [
        r"linkedin\.com/in/",
        r"instagram\.com/[a-zA-Z0-9_.]",
        r"facebook\.com/[a-zA-Z0-9.]",
        r"x\.com/[a-zA-Z0-9_]",
        r"twitter\.com/[a-zA-Z0-9_]",
        r"tiktok\.com/@",
        r"github\.com/[a-zA-Z0-9_-]",
        r"youtube\.com/(@|c/|channel/)",
        r"reddit\.com/u(ser)?/",
        r"medium\.com/@",
        r"soundcloud\.com/[a-zA-Z0-9_-]",
    ]
    return any(re.search(p, url) for p in profile_patterns)


def _extract_handle(url: str) -> str | None:
    """Extract the handle/username from a profile URL."""
    patterns = [
        (r"linkedin\.com/in/([a-zA-Z0-9_-]+)", None),
        (r"instagram\.com/([a-zA-Z0-9_.]+)", "@"),
        (r"facebook\.com/([a-zA-Z0-9.]+)", None),
        (r"x\.com/([a-zA-Z0-9_]+)", "@"),
        (r"twitter\.com/([a-zA-Z0-9_]+)", "@"),
        (r"tiktok\.com/@([a-zA-Z0-9_.]+)", "@"),
        (r"github\.com/([a-zA-Z0-9_-]+)", None),
        (r"youtube\.com/@([a-zA-Z0-9_-]+)", "@"),
        (r"reddit\.com/u(?:ser)?/([a-zA-Z0-9_-]+)", "u/"),
        (r"medium\.com/@([a-zA-Z0-9._-]+)", "@"),
        (r"soundcloud\.com/([a-zA-Z0-9_-]+)", None),
    ]
    for pattern, prefix in patterns:
        m = re.search(pattern, url)
        if m:
            handle = m.group(1)
            return f"{prefix}{handle}" if prefix else handle
    return None


def _rank_with_ai(name: str, profiles: list, groq_api_key: str) -> list:
    """Use AI to determine which profiles most likely belong to the same person."""
    try:
        profile_list = "\n".join(
            f"- {p['platform']}: {p.get('title', '')} ({p['url']})"
            for p in profiles
        )

        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You analyze search results to determine which social media "
                            "profiles likely belong to the same person. Respond ONLY in JSON: "
                            '{"ranked": [{"url": "...", "confidence": "high/medium/low", '
                            '"reason": "brief reason"}]}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Which of these profiles most likely belong to someone "
                            f'named "{name}"?\n\n{profile_list}'
                        ),
                    },
                ],
                "max_tokens": 1024,
                "temperature": 0.2,
            },
            timeout=30,
        )

        if resp.status_code != 200:
            return profiles

        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0]

        ranked = json.loads(content).get("ranked", [])

        # Merge AI ranking into profiles
        url_to_rank = {r["url"]: r for r in ranked}
        for p in profiles:
            rank_info = url_to_rank.get(p["url"], {})
            p["confidence"] = rank_info.get("confidence", "unknown")
            p["match_reason"] = rank_info.get("reason", "")

        # Sort: high > medium > low > unknown
        order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
        profiles.sort(key=lambda x: order.get(x.get("confidence", "unknown"), 3))

        return profiles

    except Exception:
        return profiles


# Need json import for _rank_with_ai
import json
