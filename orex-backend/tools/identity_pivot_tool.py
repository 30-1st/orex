import re
import httpx

# Headers that mimic a browser to avoid bot blocks
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_profile_info(url: str) -> dict:
    """
    Fetch a public profile page and extract display name, bio, and linked accounts.
    Works on platforms that serve public profile data in HTML.
    """

    url = url.strip()
    if not url.startswith("http"):
        return {"error": "Invalid URL"}

    domain = _get_domain(url)

    try:
        resp = httpx.get(
            url,
            headers=HEADERS,
            timeout=15,
            follow_redirects=True,
        )

        if resp.status_code != 200:
            return {
                "url": url,
                "platform": domain,
                "error": f"Page returned {resp.status_code}",
            }

        html = resp.text
        result = {
            "url": url,
            "platform": domain,
            "display_name": None,
            "bio": None,
            "linked_accounts": [],
            "other_info": {},
        }

        # Platform-specific extraction
        if "github.com" in domain:
            result.update(_extract_github(html))
        elif "twitter.com" in domain or "x.com" in domain:
            result.update(_extract_twitter(html))
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
        elif "tiktok.com" in domain:
            result.update(_extract_tiktok(html))
        else:
            result.update(_extract_generic(html))

        # Find linked social URLs in the page
        social_links = _find_social_links(html, url)
        if social_links:
            result["linked_accounts"] = social_links

        # Clean up None values
        result = {k: v for k, v in result.items() if v is not None and v != []}

        return result

    except httpx.TimeoutException:
        return {"url": url, "platform": domain, "error": "Page timed out"}
    except Exception as e:
        return {"url": url, "platform": domain, "error": str(e)}


def _get_domain(url: str) -> str:
    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return match.group(1) if match else url


def _meta_content(html: str, attr: str, value: str) -> str | None:
    """Extract content from a meta tag."""
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


def _extract_github(html: str) -> dict:
    info = {}
    # Display name from itemprop
    m = re.search(r'itemprop="name"[^>]*>([^<]+)', html)
    if m:
        info["display_name"] = m.group(1).strip()

    # Bio
    m = re.search(r'class="p-note user-profile-bio[^"]*"[^>]*>.*?<div>([^<]+)', html, re.DOTALL)
    if m:
        info["bio"] = m.group(1).strip()
    else:
        m = re.search(r'data-bio-text="([^"]*)"', html)
        if m:
            info["bio"] = m.group(1).strip()

    # Location
    m = re.search(r'itemprop="homeLocation"[^>]*>.*?<span[^>]*>([^<]+)', html, re.DOTALL)
    if m:
        info["other_info"] = {"location": m.group(1).strip()}

    # Company
    m = re.search(r'itemprop="worksFor"[^>]*>.*?<span[^>]*>([^<]+)', html, re.DOTALL)
    if m:
        info.setdefault("other_info", {})["company"] = m.group(1).strip()

    return info


def _extract_twitter(html: str) -> dict:
    info = {}
    title = _og(html, "title")
    if title:
        # Format: "Display Name (@handle) / X"
        m = re.match(r"(.+?)\s*\(@", title)
        if m:
            info["display_name"] = m.group(1).strip()

    desc = _og(html, "description") or _meta_content(html, "name", "description")
    if desc:
        info["bio"] = desc[:300]

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
        # Format: "Name – Medium"
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
        # Format: "Name - Title - Company | LinkedIn"
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
        # Format: "Display Name (@handle) • Instagram photos and videos"
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


def _extract_tiktok(html: str) -> dict:
    info = {}
    title = _og(html, "title")
    if title:
        # Format: "Display Name (@handle) | TikTok"
        m = re.match(r"(.+?)\s*\(@", title)
        if m:
            info["display_name"] = m.group(1).strip()

    desc = _og(html, "description")
    if desc:
        info["bio"] = desc[:300]

    return info


def _extract_generic(html: str) -> dict:
    info = {}
    title = _og(html, "title") or _meta_content(html, "name", "title")
    if title:
        info["display_name"] = title[:200]

    desc = _og(html, "description") or _meta_content(html, "name", "description")
    if desc:
        info["bio"] = desc[:300]

    return info


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

            # Skip if it's the same platform as the source
            if link_domain == source_domain:
                continue

            # Skip duplicates
            if link.lower() in seen:
                continue

            # Skip generic/common links
            if any(x in link.lower() for x in ["/share", "/intent", "/sharer", "/login", "/signup"]):
                continue

            seen.add(link.lower())
            found.append({
                "platform": link_domain,
                "url": link,
            })

    return found[:10]
