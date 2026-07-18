import re
import httpx

# Multiple user agents to rotate through
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]

import random

def _get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def extract_profile_info(url: str) -> dict:
    """
    Fetch a public profile page and extract display name, bio, and linked accounts.
    Uses platform-specific strategies with fallbacks.
    """

    url = url.strip()
    if not url.startswith("http"):
        return {"error": "Invalid URL"}

    domain = _get_domain(url)

    # Platform-specific fetch strategies
    if "twitter.com" in domain or "x.com" in domain:
        return _fetch_twitter(url, domain)
    elif "tiktok.com" in domain:
        return _fetch_tiktok(url, domain)
    else:
        return _fetch_generic(url, domain)


def _fetch_generic(url: str, domain: str) -> dict:
    """Standard fetch for most platforms."""
    try:
        resp = httpx.get(
            url,
            headers=_get_headers(),
            timeout=15,
            follow_redirects=True,
        )

        if resp.status_code != 200:
            return {"url": url, "platform": domain, "error": f"Page returned {resp.status_code}"}

        html = resp.text
        result = {
            "url": url,
            "platform": domain,
            "display_name": None,
            "bio": None,
            "linked_accounts": [],
            "other_info": {},
        }

        if "github.com" in domain:
            result.update(_extract_github(html))
        elif "reddit.com" in domain:
            result.update(_extract_reddit(html))
        elif "medium.com" in domain:
            result.update(_extract_medium(html))
        elif "linkedin.com" in domain:
            result.update(_extract_linkedin(html))
        elif "instagram.com" in domain:
            result.update(_extract_instagram(html))
        elif "facebook.com" in domain:
            result.update(_extract_facebook(html))
        else:
            result.update(_extract_generic_meta(html))

        social_links = _find_social_links(html, url)
        if social_links:
            result["linked_accounts"] = social_links

        result = {k: v for k, v in result.items() if v is not None and v != [] and v != {}}
        return result

    except httpx.TimeoutException:
        return {"url": url, "platform": domain, "error": "Page timed out"}
    except Exception as e:
        return {"url": url, "platform": domain, "error": str(e)}


# ──── Twitter/X hardened fetcher ────

def _fetch_twitter(url: str, domain: str) -> dict:
    """
    Twitter/X blocks most scrapers. Multi-strategy approach:
    1. Direct fetch with browser headers
    2. Nitter (open source Twitter frontend) instances
    3. Google cache
    4. DuckDuckGo snippet extraction
    """

    result = {
        "url": url,
        "platform": "twitter.com / x.com",
        "display_name": None,
        "bio": None,
        "linked_accounts": [],
        "other_info": {},
    }

    # Extract handle from URL
    handle = _extract_handle_from_url(url, r"(?:twitter\.com|x\.com)/([a-zA-Z0-9_]+)")
    if not handle:
        return {**result, "error": "Could not parse handle from URL"}

    # Strategy 1: Direct fetch
    try:
        resp = httpx.get(
            f"https://x.com/{handle}",
            headers=_get_headers(),
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            html = resp.text
            data = _extract_twitter_html(html)
            if data.get("display_name"):
                result.update(data)
                social_links = _find_social_links(html, url)
                if social_links:
                    result["linked_accounts"] = social_links
                return {k: v for k, v in result.items() if v is not None and v != [] and v != {}}
    except Exception:
        pass

    # Strategy 2: Try Nitter instances
    nitter_instances = [
        "nitter.privacydev.net",
        "nitter.poast.org",
        "nitter.1d4.us",
    ]
    for instance in nitter_instances:
        try:
            resp = httpx.get(
                f"https://{instance}/{handle}",
                headers=_get_headers(),
                timeout=10,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                html = resp.text
                data = _extract_nitter(html)
                if data.get("display_name"):
                    result.update(data)
                    result["source"] = f"nitter ({instance})"
                    return {k: v for k, v in result.items() if v is not None and v != [] and v != {}}
        except Exception:
            continue

    # Strategy 3: DuckDuckGo snippet
    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"site:x.com/{handle} OR site:twitter.com/{handle}"},
            headers=_get_headers(),
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            html = resp.text
            # DDG often shows the og:title in the result title
            m = re.search(
                r'class="result__a"[^>]*>([^<]*' + re.escape(handle) + r'[^<]*)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:td|div)',
                html,
                re.DOTALL | re.IGNORECASE,
            )
            if m:
                title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                snippet = re.sub(r"<[^>]+>", "", m.group(2)).strip()

                # Parse name from title: "Display Name (@handle) / X"
                name_match = re.match(r"(.+?)\s*[\(\[@]", title)
                if name_match:
                    result["display_name"] = name_match.group(1).strip()
                if snippet:
                    result["bio"] = snippet[:300]
                result["source"] = "search engine cache"
    except Exception:
        pass

    result = {k: v for k, v in result.items() if v is not None and v != [] and v != {}}
    return result


def _extract_twitter_html(html: str) -> dict:
    """Extract data from Twitter/X HTML."""
    info = {}

    title = _og(html, "title")
    if title:
        m = re.match(r"(.+?)\s*\(@", title)
        if m:
            info["display_name"] = m.group(1).strip()

    desc = _og(html, "description") or _meta_content(html, "name", "description")
    if desc:
        info["bio"] = desc[:300]

    # Try JSON-LD
    ld_match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
    if ld_match:
        try:
            import json
            ld = json.loads(ld_match.group(1))
            if isinstance(ld, dict):
                if ld.get("name") and not info.get("display_name"):
                    info["display_name"] = ld["name"]
                if ld.get("description") and not info.get("bio"):
                    info["bio"] = ld["description"][:300]
                if ld.get("url"):
                    info.setdefault("other_info", {})["canonical_url"] = ld["url"]
        except Exception:
            pass

    # Location from meta
    loc_match = re.search(r'"location":\s*"([^"]+)"', html)
    if loc_match and loc_match.group(1).strip():
        info.setdefault("other_info", {})["location"] = loc_match.group(1).strip()

    return info


def _extract_nitter(html: str) -> dict:
    """Extract data from Nitter HTML."""
    info = {}

    # Nitter display name
    m = re.search(r'class="profile-card-fullname"[^>]*>([^<]+)', html)
    if m:
        info["display_name"] = m.group(1).strip()

    # Nitter bio
    m = re.search(r'class="profile-bio"[^>]*>(.*?)</p>', html, re.DOTALL)
    if m:
        bio = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if bio:
            info["bio"] = bio[:300]

    # Nitter location
    m = re.search(r'class="profile-location"[^>]*>([^<]+)', html)
    if m:
        loc = m.group(1).strip()
        if loc:
            info.setdefault("other_info", {})["location"] = loc

    # Nitter website
    m = re.search(r'class="profile-website"[^>]*>.*?href="([^"]+)"', html, re.DOTALL)
    if m:
        info.setdefault("other_info", {})["website"] = m.group(1)

    # Nitter joined date
    m = re.search(r'class="profile-joindate"[^>]*>.*?title="([^"]+)"', html, re.DOTALL)
    if m:
        info.setdefault("other_info", {})["joined"] = m.group(1)

    return info


# ──── TikTok hardened fetcher ────

def _fetch_tiktok(url: str, domain: str) -> dict:
    """
    TikTok serves a JS-heavy page. Multi-strategy:
    1. Direct fetch (sometimes works, TikTok SSR has some meta tags)
    2. TikTok oembed API (free, no auth)
    3. DuckDuckGo snippet
    """

    result = {
        "url": url,
        "platform": "tiktok.com",
        "display_name": None,
        "bio": None,
        "linked_accounts": [],
        "other_info": {},
    }

    handle = _extract_handle_from_url(url, r"tiktok\.com/@([a-zA-Z0-9_.]+)")
    if not handle:
        return {**result, "error": "Could not parse handle from URL"}

    # Strategy 1: Direct fetch
    try:
        resp = httpx.get(
            f"https://www.tiktok.com/@{handle}",
            headers=_get_headers(),
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            html = resp.text
            data = _extract_tiktok_html(html)
            if data.get("display_name"):
                result.update(data)
                social_links = _find_social_links(html, url)
                if social_links:
                    result["linked_accounts"] = social_links
                return {k: v for k, v in result.items() if v is not None and v != [] and v != {}}
    except Exception:
        pass

    # Strategy 2: TikTok oEmbed API (free, reliable)
    try:
        resp = httpx.get(
            "https://www.tiktok.com/oembed",
            params={"url": f"https://www.tiktok.com/@{handle}"},
            headers={"User-Agent": "Orex.ai"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("author_name"):
                result["display_name"] = data["author_name"]
            if data.get("title"):
                result["bio"] = data["title"][:300]
            result["source"] = "TikTok oEmbed API"
            return {k: v for k, v in result.items() if v is not None and v != [] and v != {}}
    except Exception:
        pass

    # Strategy 3: DuckDuckGo snippet
    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"site:tiktok.com/@{handle}"},
            headers=_get_headers(),
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            html = resp.text
            m = re.search(
                r'class="result__a"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:td|div)',
                html,
                re.DOTALL,
            )
            if m:
                title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                snippet = re.sub(r"<[^>]+>", "", m.group(2)).strip()

                name_match = re.match(r"(.+?)\s*[\(\[@]", title)
                if name_match:
                    result["display_name"] = name_match.group(1).strip()
                elif "|" in title:
                    result["display_name"] = title.split("|")[0].strip()
                if snippet:
                    result["bio"] = snippet[:300]
                result["source"] = "search engine cache"
    except Exception:
        pass

    result = {k: v for k, v in result.items() if v is not None and v != [] and v != {}}
    return result


def _extract_tiktok_html(html: str) -> dict:
    """Extract data from TikTok HTML — handles both SSR and meta tags."""
    info = {}

    # og:title — "Display Name (@handle) | TikTok"
    title = _og(html, "title")
    if title:
        m = re.match(r"(.+?)\s*\(@", title)
        if m:
            info["display_name"] = m.group(1).strip()

    desc = _og(html, "description")
    if desc:
        info["bio"] = desc[:300]

        # Extract follower/following/likes from description
        counts = re.search(
            r"([\d.]+[KMBkmb]?)\s*Followers?,?\s*([\d.]+[KMBkmb]?)\s*Following,?\s*([\d.]+[KMBkmb]?)\s*Likes?",
            desc,
        )
        if counts:
            info.setdefault("other_info", {}).update({
                "followers": counts.group(1),
                "following": counts.group(2),
                "likes": counts.group(3),
            })

    # Try to find JSON data embedded in script tags
    # TikTok sometimes includes __UNIVERSAL_DATA_FOR_REHYDRATION__
    json_match = re.search(
        r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if json_match:
        try:
            import json
            data = json.loads(json_match.group(1))
            # Navigate the nested structure for user info
            user_data = (
                data.get("__DEFAULT_SCOPE__", {})
                .get("webapp.user-detail", {})
                .get("userInfo", {})
            )
            user = user_data.get("user", {})
            stats = user_data.get("stats", {})

            if user.get("nickname") and not info.get("display_name"):
                info["display_name"] = user["nickname"]
            if user.get("signature") and not info.get("bio"):
                info["bio"] = user["signature"][:300]
            if user.get("verified"):
                info.setdefault("other_info", {})["verified"] = True
            if user.get("region"):
                info.setdefault("other_info", {})["region"] = user["region"]
            if user.get("bioLink", {}).get("link"):
                info.setdefault("other_info", {})["bio_link"] = user["bioLink"]["link"]

            if stats:
                info.setdefault("other_info", {}).update({
                    "followers": stats.get("followerCount"),
                    "following": stats.get("followingCount"),
                    "likes": stats.get("heartCount"),
                    "videos": stats.get("videoCount"),
                })
        except Exception:
            pass

    return info


# ──── Standard platform extractors ────

def _extract_github(html: str) -> dict:
    info = {}
    m = re.search(r'itemprop="name"[^>]*>([^<]+)', html)
    if m:
        info["display_name"] = m.group(1).strip()

    m = re.search(r'data-bio-text="([^"]*)"', html)
    if m:
        info["bio"] = m.group(1).strip()
    else:
        m = re.search(r'class="p-note user-profile-bio[^"]*"[^>]*>.*?<div>([^<]+)', html, re.DOTALL)
        if m:
            info["bio"] = m.group(1).strip()

    m = re.search(r'itemprop="homeLocation"[^>]*>.*?<span[^>]*>([^<]+)', html, re.DOTALL)
    if m:
        info.setdefault("other_info", {})["location"] = m.group(1).strip()

    m = re.search(r'itemprop="worksFor"[^>]*>.*?<span[^>]*>([^<]+)', html, re.DOTALL)
    if m:
        info.setdefault("other_info", {})["company"] = m.group(1).strip()

    return info


def _extract_reddit(html: str) -> dict:
    info = {}
    title = _og(html, "title")
    if title:
        info["display_name"] = title.replace("u/", "").strip()
    desc = _og(html, "description")
    if desc:
        info["bio"] = desc[:300]
    return info


def _extract_medium(html: str) -> dict:
    info = {}
    title = _og(html, "title")
    if title:
        name = title.split("–")[0].split("|")[0].strip()
        if name:
            info["display_name"] = name
    desc = _og(html, "description")
    if desc:
        info["bio"] = desc[:300]
    return info


def _extract_linkedin(html: str) -> dict:
    info = {}
    title = _og(html, "title")
    if title:
        name = title.split("-")[0].split("|")[0].split("–")[0].strip()
        if name and name != "LinkedIn":
            info["display_name"] = name
    desc = _og(html, "description") or _meta_content(html, "name", "description")
    if desc:
        info["bio"] = desc[:300]
    return info


def _extract_instagram(html: str) -> dict:
    info = {}
    title = _og(html, "title")
    if title:
        m = re.match(r"(.+?)\s*\(@", title)
        if m:
            info["display_name"] = m.group(1).strip()
    desc = _og(html, "description")
    if desc:
        info["bio"] = desc[:300]
    return info


def _extract_facebook(html: str) -> dict:
    info = {}
    title = _og(html, "title")
    if title and title not in ("Facebook", "Log in to Facebook"):
        info["display_name"] = title.strip()
    desc = _og(html, "description")
    if desc:
        info["bio"] = desc[:300]
    return info


def _extract_generic_meta(html: str) -> dict:
    info = {}
    title = _og(html, "title") or _meta_content(html, "name", "title")
    if title:
        info["display_name"] = title[:200]
    desc = _og(html, "description") or _meta_content(html, "name", "description")
    if desc:
        info["bio"] = desc[:300]
    return info


# ──── Helpers ────

def _get_domain(url: str) -> str:
    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return match.group(1) if match else url


def _extract_handle_from_url(url: str, pattern: str) -> str | None:
    m = re.search(pattern, url)
    return m.group(1) if m else None


def _meta_content(html: str, attr: str, value: str) -> str | None:
    patterns = [
        rf'<meta\s+{attr}="{value}"\s+content="([^"]*)"',
        rf'<meta\s+content="([^"]*)"\s+{attr}="{value}"',
        rf"<meta\s+{attr}='{value}'\s+content='([^']*)'",
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def _og(html: str, prop: str) -> str | None:
    return _meta_content(html, "property", f"og:{prop}")


def _find_social_links(html: str, source_url: str) -> list:
    """Find social media links in the page that aren't the source URL."""
    social_patterns = [
        r'https?://(?:www\.)?twitter\.com/[a-zA-Z0-9_]+',
        r'https?://(?:www\.)?x\.com/[a-zA-Z0-9_]+',
        r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.]+',
        r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9.]+',
        r'https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+',
        r'https?://(?:www\.)?github\.com/[a-zA-Z0-9_-]+',
        r'https?://(?:www\.)?youtube\.com/(?:@|c/|channel/)[a-zA-Z0-9_-]+',
        r'https?://(?:www\.)?tiktok\.com/@[a-zA-Z0-9_.]+',
        r'https?://(?:www\.)?twitch\.tv/[a-zA-Z0-9_]+',
        r'https?://(?:www\.)?reddit\.com/u(?:ser)?/[a-zA-Z0-9_-]+',
        r'https?://(?:www\.)?discord\.gg/[a-zA-Z0-9]+',
        r'https?://(?:www\.)?t\.me/[a-zA-Z0-9_]+',
        r'https?://(?:www\.)?soundcloud\.com/[a-zA-Z0-9_-]+',
        r'https?://(?:www\.)?spotify\.com/(?:user|artist)/[a-zA-Z0-9]+',
        r'https?://(?:www\.)?medium\.com/@[a-zA-Z0-9._-]+',
    ]

    source_domain = _get_domain(source_url)
    found = []
    seen = set()

    for pattern in social_patterns:
        for match in re.finditer(pattern, html):
            link = match.group(0).rstrip("/")
            link_domain = _get_domain(link)

            if link_domain == source_domain:
                continue
            if link.lower() in seen:
                continue
            if any(x in link.lower() for x in ["/share", "/intent", "/sharer", "/login", "/signup"]):
                continue

            seen.add(link.lower())
            found.append({"platform": link_domain, "url": link})

    return found[:10]
