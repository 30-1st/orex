import re
import json
import httpx
from urllib.parse import quote

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def scrape_instagram_deep(username: str) -> dict:
    """
    Deep Instagram scraper — no login required.
    1. Scrape public profile page for all available metadata
    2. Google dork for indexed posts, tagged locations, comments, mentions
    3. Check Wayback Machine for historical profile snapshots
    """

    clean = re.sub(r"[^a-zA-Z0-9._]", "", username.strip().lstrip("@"))
    if not clean:
        return {"error": "Invalid username"}

    result = {
        "username": clean,
        "profile_data": {},
        "indexed_posts": [],
        "tagged_locations": [],
        "mentions_and_tags": [],
        "historical_snapshots": [],
    }

    # ──── 1. Scrape public profile page ────
    profile = _scrape_profile(clean)
    result["profile_data"] = profile

    # ──── 2. Google dork for indexed Instagram content ────
    # Find indexed posts
    post_results = _duckduckgo_search(
        f'site:instagram.com/p/ "{clean}"'
    )
    result["indexed_posts"] = post_results

    # Find location-tagged posts
    location_results = _duckduckgo_search(
        f'site:instagram.com "{clean}" location OR "was at" OR "checked in"'
    )
    result["tagged_locations"] = location_results

    # Find mentions by other accounts
    mention_results = _duckduckgo_search(
        f'site:instagram.com "@{clean}" -site:instagram.com/{clean}'
    )
    result["mentions_and_tags"] = mention_results

    # Find the username mentioned outside Instagram with context
    external_results = _duckduckgo_search(
        f'"instagram.com/{clean}" OR "@{clean}" -site:instagram.com'
    )
    result["external_mentions"] = external_results

    # ──── 3. Wayback Machine snapshots ────
    snapshots = _check_wayback(f"https://www.instagram.com/{clean}/")
    result["historical_snapshots"] = snapshots

    return result


def _scrape_profile(username: str) -> dict:
    """Scrape Instagram public profile page for metadata."""
    try:
        resp = httpx.get(
            f"https://www.instagram.com/{username}/",
            headers=HEADERS,
            timeout=15,
            follow_redirects=True,
        )

        if resp.status_code != 200:
            return {"error": f"Profile returned {resp.status_code}"}

        html = resp.text
        data = {}

        # Display name from og:title
        # Format: "Display Name (@handle) • Instagram photos and videos"
        og_title = _meta(html, "property", "og:title")
        if og_title:
            m = re.match(r"(.+?)\s*\(@", og_title)
            if m:
                data["display_name"] = m.group(1).strip()

        # Bio/description from og:description or meta description
        og_desc = _meta(html, "property", "og:description")
        if og_desc:
            data["description"] = og_desc[:500]

            # Extract follower/following/post counts from description
            # Format: "1,234 Followers, 567 Following, 89 Posts - ..."
            counts = re.match(
                r"([\d,.]+[KMkm]?)\s+Followers?,\s*([\d,.]+[KMkm]?)\s+Following,\s*([\d,.]+[KMkm]?)\s+Posts?",
                og_desc
            )
            if counts:
                data["followers"] = counts.group(1)
                data["following"] = counts.group(2)
                data["posts"] = counts.group(3)

            # Extract the bio text (after the counts)
            bio_match = re.search(
                r"Posts?\s*[-–—]\s*(.+)",
                og_desc
            )
            if bio_match:
                data["bio_text"] = bio_match.group(1).strip()

        # Profile pic URL from og:image
        og_image = _meta(html, "property", "og:image")
        if og_image:
            data["profile_pic_url"] = og_image

        # Check if account is verified (look for verified badge in HTML)
        if '"is_verified":true' in html or "verified" in html.lower():
            data["verified"] = True
        else:
            data["verified"] = False

        # Check if private
        if '"is_private":true' in html:
            data["is_private"] = True
            data["note"] = "Account is private — limited public data available"
        else:
            data["is_private"] = False

        # Business category
        cat_match = re.search(r'"category_name":"([^"]+)"', html)
        if cat_match:
            data["business_category"] = cat_match.group(1)

        # External URL in bio
        url_match = re.search(r'"external_url":"([^"]+)"', html)
        if url_match:
            data["bio_link"] = url_match.group(1).replace("\\u0026", "&").replace("\\/", "/")

        # Connected Facebook page
        fb_match = re.search(r'"connected_fb_page":"([^"]+)"', html)
        if fb_match:
            data["connected_facebook"] = fb_match.group(1)

        # Try to find linked accounts from bio text
        if data.get("bio_text"):
            links = _find_handles_in_bio(data["bio_text"])
            if links:
                data["handles_in_bio"] = links

        return data

    except Exception as e:
        return {"error": str(e)}


def _find_handles_in_bio(bio: str) -> list:
    """Extract social handles and links from bio text."""
    handles = []

    # Twitter/X handles
    for m in re.finditer(r"(?:twitter|x)(?:\.com/|:\s*@?)([a-zA-Z0-9_]+)", bio, re.IGNORECASE):
        handles.append({"platform": "Twitter/X", "handle": f"@{m.group(1)}"})

    # TikTok handles
    for m in re.finditer(r"(?:tiktok|tik tok)(?:\.com/@?|:\s*@?)([a-zA-Z0-9_.]+)", bio, re.IGNORECASE):
        handles.append({"platform": "TikTok", "handle": f"@{m.group(1)}"})

    # YouTube
    for m in re.finditer(r"(?:youtube|yt)(?:\.com/(?:@|c/)?|:\s*)([a-zA-Z0-9_-]+)", bio, re.IGNORECASE):
        handles.append({"platform": "YouTube", "handle": m.group(1)})

    # Snapchat
    for m in re.finditer(r"(?:snapchat|snap)(?:\.com/add/|:\s*@?)([a-zA-Z0-9_.-]+)", bio, re.IGNORECASE):
        handles.append({"platform": "Snapchat", "handle": m.group(1)})

    # Generic @ handles (catch others)
    for m in re.finditer(r"@([a-zA-Z0-9_.]{2,30})", bio):
        handle = m.group(1)
        # Skip if already captured
        if not any(h["handle"].lstrip("@") == handle for h in handles):
            handles.append({"platform": "unknown", "handle": f"@{handle}"})

    # URLs
    for m in re.finditer(r"(https?://[^\s,]+)", bio):
        url = m.group(1).rstrip(".,;)")
        handles.append({"platform": "link", "url": url})

    return handles


def _meta(html: str, attr: str, value: str) -> str | None:
    """Extract content from a meta tag."""
    patterns = [
        rf'<meta\s+{attr}="{value}"\s+content="([^"]*)"',
        rf'<meta\s+content="([^"]*)"\s+{attr}="{value}"',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def _duckduckgo_search(query: str) -> list:
    """Search DuckDuckGo for results."""
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
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        for url, title in matches[:5]:
            if "uddg=" in url:
                m = re.search(r"uddg=([^&]+)", url)
                if m:
                    from urllib.parse import unquote
                    url = unquote(m.group(1))

            title = re.sub(r"<[^>]+>", "", title).strip()

            if title:
                results.append({
                    "url": url.rstrip("/"),
                    "title": title[:200],
                })

        return results

    except Exception:
        return []


def _check_wayback(url: str) -> list:
    """Check Wayback Machine for historical snapshots of a URL."""
    try:
        resp = httpx.get(
            "https://web.archive.org/cdx/search/cdx",
            params={
                "url": url,
                "output": "json",
                "limit": "10",
                "fl": "timestamp,original,statuscode",
                "filter": "statuscode:200",
                "collapse": "timestamp:6",  # One per month
            },
            headers={"User-Agent": "Orex.ai research@orex.ai"},
            timeout=15,
        )

        if resp.status_code != 200:
            return []

        data = resp.json()
        if len(data) <= 1:  # First row is headers
            return []

        snapshots = []
        for row in data[1:]:
            timestamp = row[0]
            year = timestamp[:4]
            month = timestamp[4:6]
            day = timestamp[6:8]

            snapshots.append({
                "date": f"{year}-{month}-{day}",
                "wayback_url": f"https://web.archive.org/web/{timestamp}/{url}",
                "note": "Historical snapshot — may reveal old display name, bio, or profile pic"
            })

        return snapshots

    except Exception:
        return []
