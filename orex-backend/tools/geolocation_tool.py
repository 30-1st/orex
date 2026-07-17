import io
import json
import base64
import httpx
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS


def _get_exif_gps(image_bytes: bytes) -> dict | None:
    """Extract GPS coordinates from image EXIF data."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        exif_data = img._getexif()
        if not exif_data:
            return None

        gps_info = {}
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "GPSInfo":
                for gps_tag_id, gps_value in value.items():
                    gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                    gps_info[gps_tag] = gps_value

        if not gps_info or "GPSLatitude" not in gps_info:
            return None

        def dms_to_decimal(dms, ref):
            d, m, s = [float(x) for x in dms]
            decimal = d + m / 60 + s / 3600
            if ref in ("S", "W"):
                decimal = -decimal
            return decimal

        lat = dms_to_decimal(
            gps_info["GPSLatitude"],
            gps_info.get("GPSLatitudeRef", "N")
        )
        lon = dms_to_decimal(
            gps_info["GPSLongitude"],
            gps_info.get("GPSLongitudeRef", "E")
        )

        return {
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "source": "EXIF metadata",
            "confidence": "exact",
            "map_url": f"https://www.google.com/maps?q={lat},{lon}",
        }

    except Exception:
        return None


def _reverse_geocode(lat: float, lon: float) -> dict:
    """Get address from coordinates using free Nominatim API."""
    try:
        resp = httpx.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lon,
                "format": "json",
                "zoom": 18,
                "addressdetails": 1,
            },
            headers={"User-Agent": "Orex.ai research@orex.ai"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "display_name": data.get("display_name", ""),
                "address": data.get("address", {}),
            }
    except Exception:
        pass
    return {}


def analyze_image_location(image_base64: str, groq_api_key: str) -> dict:
    """
    Analyze an image to determine where it was taken.
    First checks EXIF, then falls back to AI vision analysis.
    """

    # Decode base64 image
    try:
        # Handle data URL prefix if present
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]
        image_bytes = base64.b64decode(image_base64)
    except Exception as e:
        return {"error": f"Invalid image data: {str(e)}"}

    # Layer 1: Check EXIF
    exif_result = _get_exif_gps(image_bytes)
    if exif_result:
        # Enrich with reverse geocoding
        geo = _reverse_geocode(exif_result["latitude"], exif_result["longitude"])
        if geo:
            exif_result["address"] = geo.get("display_name", "")
            exif_result["address_details"] = geo.get("address", {})
        return exif_result

    # Layer 2: AI Vision analysis
    try:
        b64_str = base64.b64encode(image_bytes).decode("utf-8")

        # Detect mime type
        if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            mime = "image/png"
        elif image_bytes[:2] == b'\xff\xd8':
            mime = "image/jpeg"
        elif image_bytes[:4] == b'RIFF':
            mime = "image/webp"
        else:
            mime = "image/jpeg"

        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a geolocation expert. Analyze images to determine "
                            "where they were taken. Look for: street signs, language on signs, "
                            "architecture style, vegetation, road markings, license plates, "
                            "terrain, sun position, brand names, infrastructure style, "
                            "utility poles, building materials, and any other visual clues. "
                            "Respond ONLY in JSON with these fields: "
                            '{"estimated_location": "City, State/Region, Country", '
                            '"confidence": "high/medium/low", '
                            '"latitude": number_or_null, '
                            '"longitude": number_or_null, '
                            '"clues": ["list of visual clues you identified"], '
                            '"reasoning": "brief explanation"} '
                            "No other text, just JSON."
                        )
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{b64_str}"
                                }
                            },
                            {
                                "type": "text",
                                "text": "Where was this image taken? Analyze all visual clues."
                            }
                        ]
                    }
                ],
                "max_tokens": 1024,
                "temperature": 0.3,
            },
            timeout=60,
        )

        if resp.status_code != 200:
            return {
                "error": f"Vision model returned {resp.status_code}",
                "source": "AI vision analysis",
            }

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON from response
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0]

        result = json.loads(content)
        result["source"] = "AI vision analysis"

        # Add map link if coordinates found
        if result.get("latitude") and result.get("longitude"):
            result["map_url"] = (
                f"https://www.google.com/maps?q={result['latitude']},{result['longitude']}"
            )
            # Reverse geocode the AI estimate
            geo = _reverse_geocode(result["latitude"], result["longitude"])
            if geo:
                result["address"] = geo.get("display_name", "")

        return result

    except json.JSONDecodeError:
        return {
            "estimated_location": content if content else "Unable to determine",
            "confidence": "low",
            "source": "AI vision analysis",
            "error": "Could not parse structured response",
        }
    except Exception as e:
        return {"error": str(e), "source": "AI vision analysis"}
