import re
import json
import httpx
from urllib.parse import quote

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def deep_investigate(username: str, profile_pic_url: str = None, bio_links: list = None) -> dict:
    """
    Deep investigation on a username:
    1. Google dork across the web for real name mentions tied to the username
    2. Dating app profile discovery
    3. WHOIS lookup on any domains linked in bio
    4. Reverse image search pointers for profile picture
    """

    clean = re.sub(r"[^a-zA-Z0-9._-]", "", username.strip().lstrip("@"))
    if not clean:
        return {"error": "Invalid username"}

    result = {
        "username": clean,
        "web_mentions": [],
        "dating_profiles": [],
        "whois_results": [],
        "reverse_image": None,
    }

    # ──── 1. Identity dorking ────
    dork_queries = [
        f'"{clean}" real name',
        f'"{clean}" name is',
        f'"{clean}" known as',
        f'"{clean}" -site:instagram.com -site:twitter.com -site:tiktok.com',
        f'"{clean}" photographer OR artist OR developer OR engineer OR designer',
        f'"{clean}" interview OR article OR featured OR profile',
        f'"{clean}" site:linkedin.com OR site:facebook.com',
        f'"{clean}" "@gmail.com" OR "@yahoo.com" OR "@hotmail.com" OR "@outlook.com"',
        # Forum/community posts where people use real names
        f'"{clean}" "my name is" OR "I\'m" OR "call me"',
        # Portfolio/personal sites
        f'"{clean}" portfolio OR resume OR CV OR "about me"',
    ]

    for query in dork_queries:
        mentions = _search_duckduckgo(query)
        for m in mentions:
            if not any(existing["url"] == m["url"] for existing in result["web_mentions"]):
                result["web_mentions"].append(m)

    # ──── 2. Dating app discovery ────
    dating_queries = [
        # Direct platform searches
        f'"{clean}" site:tinder.com OR site:bumble.com OR site:hinge.co',
        f'"{clean}" site:match.com OR site:okcupid.com OR site:pof.com',
        f'"{clean}" site:zoosk.com OR site:eharmony.com OR site:coffee-meets-bagel.com',
        # Indexed dating profile pages
        f'"{clean}" "looking for" "relationship" tinder OR bumble OR hinge',
        # Username referenced with dating context
        f'"{clean}" "swipe right" OR "matched with" OR "my profile"',
        # Reviews/screenshots of dating profiles shared online
        f'"{clean}" dating profile OR dating app',
    ]

    for query in dating_queries:
        mentions = _search_duckduckgo(query)
        for m in mentions:
            if not any(existing["url"] == m["url"] for existing in result["dating_profiles"]):
                result["dating_profiles"].append(m)

    # ──── 3. WHOIS on bio links ────
    if bio_links:
        for link in bio_links[:3]:
            domain = _extract_domain(link)
            if domain and not _is_social_domain(domain):
                whois_data = _whois_lookup(domain)
                if whois_data:
                    result["whois_results"].append(whois_data)

    # ──── 4. Reverse image search ────
    if profile_pic_url:
        result["reverse_image"] = {
            "note": "Profile picture URL available for reverse image search",
            "profile_pic_url": profile_pic_url,
            "search_urls": {
                "google_lens": f"https://lens.google.com/uploadbyurl?url={quote(profile_pic_url)}",
                "tineye": f"https://tineye.com/search?url={quote(profile_pic_url)}",
                "yandex": f"https://yandex.com/images/search?rpt=imageview&url={quote(profile_pic_url)}",
            },
            "instruction": "Use these URLs to reverse search the profile picture for other pages showing the same face with a real name attached."
        }
    else:
        result["reverse_image"] = {
            "note": "No profile picture URL provided. If available, reverse image search can reveal other pages with the same photo tied to a real name.",
        }

    result["total_web_mentions"] = len(result["web_mentions"])
    result["total_dating_hits"] = len(result["dating_profiles"])

    return result


def _search_duckduckgo(query: str) -> list:
    """Search DuckDuckGo HTML for results."""
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

        matches = re.findall(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
            html,
            re.DOTALL,
        )

        for url, title, snippet in matches[:5]:
            if "uddg=" in url:
                m = re.search(r"uddg=([^&]+)", url)
                if m:
                    from urllib.parse import unquote
                    url = unquote(m.group(1))

            title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()

            if title or snippet:
                results.append({
                    "url": url,
                    "title": title[:200],
                    "snippet": snippet[:300],
                })

        return results

    except Exception:
        return []


def _extract_domain(url: str) -> str | None:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    if m:
        domain = m.group(1)
        if re.match(r"\d+\.\d+\.\d+\.\d+", domain):
            return None
        return domain
    return None


def _is_social_domain(domain: str) -> bool:
    social = [
        "instagram.com", "twitter.com", "x.com", "facebook.com",
        "tiktok.com", "linkedin.com", "youtube.com", "reddit.com",
        "snapchat.com", "pinterest.com", "tumblr.com", "twitch.tv",
        "discord.com", "discord.gg", "telegram.org", "t.me",
        "linktr.ee", "linktree.com", "beacons.ai", "bio.link",
        "carrd.co", "about.me",
    ]
    return any(domain.endswith(s) or domain == s for s in social)


def _whois_lookup(domain: str) -> dict | None:
    try:
        resp = httpx.get(
            f"https://rdap.org/domain/{domain}",
            headers={"Accept": "application/rdap+json"},
            timeout=15,
            follow_redirects=True,
        )

        if resp.status_code != 200:
            return None

        data = resp.json()
        result = {"domain": domain}

        entities = data.get("entities", [])
        for entity in entities:
            roles = entity.get("roles", [])
            vcard = entity.get("vcardArray", [])

            if any(r in roles for r in ["registrant", "administrative", "technical"]):
                if len(vcard) > 1:
                    for field in vcard[1]:
                        if field[0] == "fn":
                            name = field[3]
                            if name and name.lower() not in ("redacted", "data protected", "privacy", "contact privacy", "redacted for privacy"):
                                result["registrant_name"] = name
                        elif field[0] == "org":
                            org = field[3]
                            if org and org.lower() not in ("redacted", "data protected", "privacy"):
                                result["registrant_org"] = org
                        elif field[0] == "adr":
                            if isinstance(field[3], list):
                                addr = " ".join(str(x) for x in field[3] if x and str(x).lower() not in ("redacted", ""))
                                if addr.strip():
                                    result["registrant_location"] = addr.strip()
                        elif field[0] == "email":
                            email = field[3]
                            if email and "@" in email and "privacy" not in email.lower() and "redacted" not in email.lower():
                                result["registrant_email"] = email

        events = data.get("events", [])
        for event in events:
            if event.get("eventAction") == "registration":
                result["registered_date"] = event.get("eventDate", "")
            elif event.get("eventAction") == "expiration":
                result["expiry_date"] = event.get("eventDate", "")

        if len(result) > 1:
            return result

        return None

    except Exception:
        return None
