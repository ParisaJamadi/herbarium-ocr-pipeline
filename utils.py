"""
Shared utilities for herbarium extraction pipeline.
"""

import base64
import os
import re
import sys
import time
import requests
from urllib.parse import urlparse, quote, unquote

# Printed once when the Zenodo IP-block is first detected
_ZENODO_IP_BLOCK_WARNED = False

EXTRACTION_PROMPT = """You are an expert botanist and herbarium curator. Examine this herbarium sheet image carefully.

Extract ALL of the following fields from labels, stamps, handwritten text, and printed text visible on the sheet:

Return a JSON object with EXACTLY these fields (use null for any field not found):
{
  "scientific_name": "full scientific name including author if present",
  "family": "plant family — look for it printed on any label or stamp; also infer from scientific name if clearly identifiable (e.g. Rosa → Rosaceae)",
  "genus": "genus name only",
  "collector": "person(s) who collected the specimen",
  "collection_date": "date as written on label (verbatim)",
  "collection_date_normalized": "date in YYYY-MM-DD format if possible, else null",
  "locality": "location description as written",
  "country": "country name",
  "habitat": "habitat description if present",
  "elevation": "elevation as written (with units)",
  "type_status": "e.g. HOLOTYPE, ISOTYPE, PARATYPE, or null if not a type",
  "institution_code": "herbarium/institution abbreviation (e.g. K, BM, E, P)",
  "barcode": "specimen barcode or accession number",
  "identified_by": "person who identified/determined the species",
  "identification_date": "date of identification if present",
  "field_notes": "any additional notes on the label",
  "label_language": "primary language of labels (e.g. English, Latin, French)",
  "image_quality": "good/fair/poor - assess legibility of labels",
  "confidence": "overall confidence in extraction: high/medium/low"
}

Return ONLY valid JSON, no explanation or markdown fences.
"""

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

# Regex to extract Zenodo record_id and filename from file URLs
_ZENODO_FILE_RE = re.compile(
    r"zenodo\.org/records?/(\d+)/files/([^?#]+)"
)

# UUID pattern for BM (Natural History Museum) specimens
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


# ---------------------------------------------------------------------------
# Zenodo helpers
# ---------------------------------------------------------------------------

def _is_zenodo_ip_block(response: requests.Response) -> bool:
    """Return True when Zenodo has blocked this IP for 'unusual traffic'."""
    if response.status_code != 403:
        return False
    body = response.text.lower()
    return "unusual traffic" in body or "access to this resource has been restricted" in body


def _warn_zenodo_ip_block_once():
    global _ZENODO_IP_BLOCK_WARNED
    if _ZENODO_IP_BLOCK_WARNED:
        return
    _ZENODO_IP_BLOCK_WARNED = True
    print(
        "\n  ⛔ Zenodo has blocked your IP/network — falling back to institution portals.\n"
        "  If institution fallback also fails, see README Troubleshooting.\n",
        file=sys.stderr,
    )


def _try_zenodo_api(record_id: str, filename: str, timeout: int) -> tuple:
    """
    Download via the Zenodo REST API (/api/records/{id}/files/{name}/content).
    Supports an optional ZENODO_ACCESS_TOKEN env var.

    NOTE: uses a plain session without browser headers — Zenodo's bot-protection
    blocks authenticated API calls that carry a browser User-Agent.
    """
    token = os.environ.get("ZENODO_ACCESS_TOKEN")
    api_url = f"https://zenodo.org/api/records/{record_id}/files/{filename}/content"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        # Use requests directly (not _SESSION) so no browser UA is sent
        r = requests.get(api_url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            # Zenodo sometimes returns "image/jpeg, image/jpeg" — take only first value
            raw_ct = r.headers.get("content-type", "").split(";")[0].strip()
            content_type = raw_ct.split(",")[0].strip()
            if not content_type.startswith("image/"):
                content_type = _sniff_image_type(r.content)
            if content_type.startswith("image/") and len(r.content) >= 100:
                return base64.standard_b64encode(r.content).decode("utf-8"), content_type
        if _is_zenodo_ip_block(r):
            _warn_zenodo_ip_block_once()
    except Exception:
        pass
    return None, None


# ---------------------------------------------------------------------------
# Institution-portal fallbacks
# ---------------------------------------------------------------------------

def _occurrence_id_to_institution(occurrence_id: str) -> tuple:
    """
    Parse an occurrenceID and return (institution_hint, catalog_number).

    institution_hint values:
        'bm'        – Natural History Museum, London (UUID occurrenceID)
        'kew'       – Royal Botanic Gardens Kew
        'bgbm'      – Botanic Garden & Botanical Museum Berlin
        'helsinki'  – Finnish Museum of Natural History / Luomus
        'rbge'      – Royal Botanic Garden Edinburgh (requires auth — skipped)
        'naturalis' – Naturalis Biodiversity Center Leiden
        'paris'     – Muséum national d'Histoire naturelle Paris (blocked)
        'brussels'  – Meise Botanic Garden Belgium (blocked)
        'unknown'   – unrecognised institution
    """
    occ = (occurrence_id or "").strip()

    if _UUID_RE.match(occ):
        return "bm", occ

    catalog = unquote(occ.rstrip("/").split("/")[-1]) if "/" in occ else unquote(occ)
    occ_l = occ.lower()

    if "rbge.org.uk" in occ_l or "data.rbge" in occ_l:
        return "rbge", catalog
    if "specimens.kew.org" in occ_l:
        return "kew", catalog
    if "bgbm.org" in occ_l:
        return "bgbm", catalog
    if "id.luomus.fi" in occ_l or "luomus" in occ_l:
        return "helsinki", catalog
    if "biodiversitydata.nl" in occ_l or "naturalis" in occ_l:
        return "naturalis", catalog
    if "mnhn.fr" in occ_l:
        return "paris", catalog
    if "botanicalcollections.be" in occ_l:
        return "brussels", catalog
    return "unknown", catalog


def _bgbm_catalog_to_gbif_format(catalog: str) -> str:
    """
    Convert BGBM URL barcode (e.g. 'B100003484') to GBIF storage format ('B 10 0003484').
    GBIF stores Berlin specimens with spaces: B {2 chars} {remainder}.
    """
    if catalog.startswith("B") and len(catalog) >= 4:
        return catalog[0] + " " + catalog[1:3] + " " + catalog[3:]
    return catalog


_IMAGE_MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"GIF8": "image/gif",
    b"RIFF": "image/webp",
}


def _sniff_image_type(content: bytes) -> str:
    """Return a content-type string from magic bytes, or empty string."""
    for magic, ct in _IMAGE_MAGIC.items():
        if content[:len(magic)] == magic:
            return ct
    return ""


def _fetch_image_url(img_url: str, timeout: int) -> tuple:
    """Download an image URL; fall back to magic-byte sniffing if no Content-Type."""
    try:
        r = _SESSION.get(img_url, timeout=timeout, allow_redirects=True)
        if r.status_code != 200 or len(r.content) < 100:
            return None, None
        ct = r.headers.get("content-type", "").split(";")[0].strip()
        if not ct.startswith("image/"):
            ct = _sniff_image_type(r.content)
        if ct.startswith("image/"):
            return base64.standard_b64encode(r.content).decode("utf-8"), ct
    except Exception:
        pass
    return None, None


def _gbif_image(catalog_number: str, timeout: int, key: str = "catalogNumber") -> tuple:
    """
    Look up a specimen on GBIF (by catalogNumber or occurrenceId) and return
    the first StillImage as (base64, content_type) or (None, None).
    """
    try:
        param = quote(catalog_number, safe="")
        url = f"https://api.gbif.org/v1/occurrence/search?{key}={param}&limit=5"
        r = _SESSION.get(url, timeout=timeout)
        if r.status_code != 200:
            return None, None
        results = r.json().get("results", [])
        for occ in results:
            for item in occ.get("media", []):
                if item.get("type") == "StillImage":
                    img_url = item.get("identifier", "")
                    if img_url:
                        result = _fetch_image_url(img_url, timeout)
                        if result[0] is not None:
                            return result
    except Exception:
        pass
    return None, None


def _bm_image(uuid: str, timeout: int) -> tuple:
    """
    Fetch BM (NHM London) image.
    The occurrence UUID differs from the internal media UUID, so we look up
    the real media URL via GBIF's occurrenceId search first.
    """
    return _gbif_image(uuid, timeout, key="occurrenceId")


def _helsinki_image(catalog: str, timeout: int) -> tuple:
    """
    Fetch Finnish Museum image via id.luomus.fi JSON API.
    The API returns a document with media[].fullURL pointing to image.laji.fi.
    """
    try:
        r = _SESSION.get(
            f"https://id.luomus.fi/{catalog}",
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            return None, None
        gatherings = r.json().get("document", {}).get("gatherings", [])
        if not gatherings:
            return None, None
        units = gatherings[0].get("units", [])
        if not units:
            return None, None
        media = units[0].get("media", [])
        if not media:
            return None, None
        img_url = media[0].get("fullURL")
        if not img_url:
            return None, None
        r2 = _SESSION.get(img_url, timeout=timeout)
        if r2.status_code == 200:
            ct = r2.headers.get("content-type", "").split(";")[0].strip()
            if ct.startswith("image/") and len(r2.content) >= 100:
                return base64.standard_b64encode(r2.content).decode("utf-8"), ct
    except Exception:
        pass
    return None, None


def fetch_institution_image(occurrence_id: str, timeout: int = 30) -> tuple:
    """
    Try to fetch a specimen image directly from the institution's own portal.
    Called as a fallback when Zenodo fails.
    Returns (base64_string, media_type) or (None, None).
    """
    institution, catalog = _occurrence_id_to_institution(occurrence_id)

    if institution == "bm":
        return _bm_image(catalog, timeout)

    if institution == "helsinki":
        return _helsinki_image(catalog, timeout)

    if institution == "bgbm":
        return _gbif_image(_bgbm_catalog_to_gbif_format(catalog), timeout)

    if institution in ("kew", "naturalis"):
        return _gbif_image(catalog, timeout)

    # rbge (401), paris (403), brussels (403), unknown — no working fallback
    return None, None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fetch_image_base64(url: str, occurrence_id: str = "", timeout: int = 30, retries: int = 3):
    """Download an image and return (base64_string, media_type) or (None, None).

    Strategy:
      1. Try Zenodo REST API (avoids bot-protection 403s)
      2. Try Zenodo direct file URL
      3. If both Zenodo paths fail and occurrence_id is given, try the
         institution's own portal (BM, Kew, BGBM, Helsinki, Naturalis)
    """
    url = url.replace("zenodo.org/record/", "zenodo.org/records/")

    # --- Zenodo REST API ---
    m = _ZENODO_FILE_RE.search(url)
    if m:
        record_id = m.group(1)
        filename = unquote(m.group(2))
        result = _try_zenodo_api(record_id, filename, timeout)
        if result[0] is not None:
            return result
        print(f"  Zenodo API failed for record {record_id}/{filename}, trying direct URL", file=sys.stderr)

    # --- Zenodo direct URL ---
    parsed = urlparse(url)
    fixed_path = quote(parsed.path, safe="/")
    query = parsed.query
    if "download=1" not in query:
        query = (query + "&download=1").lstrip("&")
    direct_url = parsed._replace(path=fixed_path, query=query).geturl()

    zenodo_ok = False
    for attempt in range(retries):
        try:
            r = _SESSION.get(direct_url, timeout=timeout)

            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5)) * (attempt + 1)
                print(f"  Rate-limited — waiting {wait}s before retry", file=sys.stderr)
                time.sleep(wait)
                continue

            if r.status_code != 200:
                if _is_zenodo_ip_block(r):
                    _warn_zenodo_ip_block_once()
                print(f"  HTTP {r.status_code} for {direct_url}", file=sys.stderr)
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                break

            content_type = r.headers.get("content-type", "").split(";")[0].strip()
            if not content_type.startswith("image/"):
                print(f"  Not an image (content-type: {content_type})", file=sys.stderr)
                break

            content = r.content
            if len(content) < 100:
                print(f"  Response too small ({len(content)} bytes)", file=sys.stderr)
                break

            zenodo_ok = True
            return base64.standard_b64encode(content).decode("utf-8"), content_type

        except requests.exceptions.Timeout:
            print(f"  Timeout (attempt {attempt + 1}/{retries})", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  Fetch error: {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    # --- Institution portal fallback ---
    if not zenodo_ok and occurrence_id:
        institution, _ = _occurrence_id_to_institution(occurrence_id)
        if institution not in ("rbge", "paris", "brussels", "unknown"):
            print(f"  Trying {institution} institution portal...", file=sys.stderr)
            result = fetch_institution_image(occurrence_id, timeout)
            if result[0] is not None:
                print(f"  ✓ Got image from {institution} portal", file=sys.stderr)
                return result
            print(f"  Institution portal also failed", file=sys.stderr)

    return None, None
