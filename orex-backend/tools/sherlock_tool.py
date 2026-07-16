import subprocess
import re
import os


def run_sherlock(username: str) -> dict:
    """Run Sherlock CLI and parse results into structured data."""

    # Sanitize input — alphanumeric, dots, underscores, hyphens only
    clean = re.sub(r"[^a-zA-Z0-9._-]", "", username.strip().lstrip("@"))
    if not clean or len(clean) > 64:
        return {"error": "Invalid username", "results": []}

    try:
        result = subprocess.run(
            [
                "maigret", clean,
                "--print-found",
                "--no-color",
                "--timeout", "15",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/tmp"
        )

        output = result.stdout
        found = []

        for line in output.splitlines():
            line = line.strip()
            # Sherlock output format: [+] SiteName: https://...
            match = re.match(r"\[\+\]\s+(.+?):\s+(https?://\S+)", line)
            if match:
                found.append({
                    "platform": match.group(1).strip(),
                    "url": match.group(2).strip()
                })

        return {
            "username": clean,
            "total_found": len(found),
            "profiles": found
        }

    except subprocess.TimeoutExpired:
        return {"error": "Search timed out", "username": clean, "profiles": []}
    except Exception as e:
        return {"error": str(e), "username": clean, "profiles": []}
