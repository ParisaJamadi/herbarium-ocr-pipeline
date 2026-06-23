"""
Ground-truth evaluation: re-extract a sample of main_data specimens (which have known values)
and measure how accurately GPT-4o's extraction matches the pre-existing metadata.

Usage:
    python evaluate_ground_truth.py --sample 20 --output gt_eval.json
    python evaluate_ground_truth.py --sample 20 --output gt_eval.json --verbose
"""

import openai
import pandas as pd
import json
import time
import argparse
import sys
from difflib import SequenceMatcher
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from utils import EXTRACTION_PROMPT, fetch_image_base64

load_dotenv()

XLSX_PATH = "techtest_herbariumdata.xlsx"
MODEL = "gpt-4o"

# Map extracted field names → ground truth column names in main_data
# NOTE on column choices:
#   locality      → "locality" (31% null), NOT "verbatimLocality" (99% null)
#   collector     → "recordedBy" (1% null), NOT "verbatimRecordedBy" (100% null)
#   elevation     → "elevation" (78% null), NOT "verbatimElevation" (87% null)
FIELD_MAP = {
    "scientific_name": "scientificName",
    "family": "family",
    "genus": "genus",
    "country": "country",
    "locality": "locality",
    "elevation": "elevation",
    "collector": "recordedBy",
    "type_status": "typeStatus",
    "institution_code": "institutionCode",
    "habitat": "habitat",
    "identified_by": "identifiedBy",
}


INSTITUTION_ALIASES = {
    # GT column stores short codes; GPT-4o may return full names or different codes
    "rbge": "e",
    "royal botanic garden edinburgh": "e",
    "nhmuk": "nhmuk",
    "nhm": "nhmuk",
    "natural history museum": "nhmuk",
    "bm": "nhmuk",
    "k": "k",
    "kew": "k",
    "royal botanic gardens kew": "k",
    "naturalis": "l",
    "l": "l",
    "bgbm": "b",
    "b": "b",
    "botanischer garten berlin": "b",
    "mnhn": "mnhn",
    "p": "mnhn",
    "paris": "mnhn",
    "br": "br",
    "meise": "br",
}


def _norm_elevation(v) -> str:
    """Strip units and normalise elevation to metres as a plain integer string.
    Handles: '1200 m', '7000 ft', '7000 FT', '0-30 m', 2630.0 (float from GT)."""
    import re
    s = str(v).lower().strip()
    is_feet = bool(re.search(r"\bft\b|\bfeet\b|\bfoot\b", s))

    # Handle ranges like "0-30 m" → take midpoint
    range_match = re.match(r"(\d+(?:\.\d+)?)\s*[-\u2013]\s*(\d+(?:\.\d+)?)", s)
    if range_match:
        mid = (float(range_match.group(1)) + float(range_match.group(2))) / 2
        metres = mid * 0.3048 if is_feet else mid
        return str(int(round(metres)))

    num_match = re.match(r"(\d+(?:\.\d+)?)", s)
    if num_match:
        val = float(num_match.group(1))
        metres = val * 0.3048 if is_feet else val
        return str(int(round(metres)))
    return s


def _norm_scientific_name(v) -> str:
    """Return first two tokens (genus + species epithet), dropping author citations."""
    parts = str(v).strip().split()
    return " ".join(parts[:2]).lower() if len(parts) >= 2 else str(v).lower().strip()


def _norm_collector(v) -> str:
    """Normalise collector name: 'Smith, J.' and 'J. Smith' both → 'smith j'."""
    import re
    s = re.sub(r"[^\w\s]", " ", str(v)).lower()
    tokens = [t for t in s.split() if len(t) > 1 or t.isalpha()]
    return " ".join(sorted(tokens))  # sort tokens to handle reordered name parts


def _norm_institution(v) -> str:
    s = str(v).lower().strip()
    return INSTITUTION_ALIASES.get(s, s)


def normalize(value, field: str) -> str:
    """Field-specific normalization before fuzzy comparison."""
    if pd.isna(value) or str(value) == "nan":
        return None
    if field == "elevation":
        return _norm_elevation(value)
    if field == "scientific_name":
        return _norm_scientific_name(value)
    if field == "collector":
        return _norm_collector(value)
    if field == "institution_code":
        return _norm_institution(value)
    return str(value).lower().strip()


def fuzzy(a, b, field: str = ""):
    """Fuzzy string similarity (0–1) with field-aware normalisation. Returns None if either is null."""
    na = normalize(a, field)
    nb = normalize(b, field)
    if na is None or nb is None:
        return None
    return SequenceMatcher(None, na, nb).ratio()


def extract(client: openai.OpenAI, img_b64: str, media_type: str) -> dict:
    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{img_b64}",
                            "detail": "high"
                        }
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT}
                ]
            }]
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        return json.loads(raw.strip())
    except Exception as e:
        return {"extraction_error": str(e)}


def run_gt_eval(sample_size: int, output_path: str, delay: float = 1.5, verbose: bool = False):
    client = openai.OpenAI()
    df = pd.read_excel(XLSX_PATH, sheet_name="main_data")

    valid = df[df["jpegURL"].notna() & df["scientificName"].notna()]
    sample = valid.sample(n=min(sample_size, len(valid)), random_state=99).reset_index(drop=True)

    print(f"Model: {MODEL}")
    print(f"Ground-truth evaluation on {len(sample)} main_data specimens...\n")

    records = []
    field_sims = {f: [] for f in FIELD_MAP}

    for i, row in sample.iterrows():
        print(f"[{i+1}/{len(sample)}] {row['occurrenceID']}")

        img_b64, mtype = fetch_image_base64(row["jpegURL"], occurrence_id=str(row.get("occurrenceID", "")))
        if not img_b64:
            print("  Skipping — image fetch failed")
            continue

        extracted = extract(client, img_b64, mtype)
        if "extraction_error" in extracted:
            print(f"  Error: {extracted['extraction_error']}")
            continue

        row_result = {"occurrenceID": row["occurrenceID"]}
        sims_this_row = []

        for ext_f, gt_f in FIELD_MAP.items():
            ext_val = extracted.get(ext_f)
            gt_val = row.get(gt_f)
            sim = fuzzy(ext_val, gt_val, field=ext_f)
            row_result[f"ext_{ext_f}"] = ext_val
            row_result[f"gt_{gt_f}"] = gt_val
            row_result[f"sim_{ext_f}"] = round(sim, 4) if sim is not None else None
            if sim is not None:
                field_sims[ext_f].append(sim)
                sims_this_row.append(sim)

            if verbose:
                flag = "✓" if sim == 1.0 else ("~" if sim and sim > 0.7 else "✗")
                sim_str = f"{sim:.2f}" if sim is not None else "N/A"
                print(f"  {flag} {ext_f}: extracted={ext_val!r}  gt={gt_val!r}  sim={sim_str}")

        row_result["confidence"] = extracted.get("confidence")
        row_result["image_quality"] = extracted.get("image_quality")
        records.append(row_result)

        avg_sim = sum(sims_this_row) / len(sims_this_row) if sims_this_row else 0
        print(f"  avg_sim={avg_sim:.2f}  name_sim={row_result.get('sim_scientific_name', 'N/A')}  conf={extracted.get('confidence')}")

        if i < len(sample) - 1:
            time.sleep(delay)

    # Save detailed CSV
    df_out = pd.DataFrame(records)
    csv_path = output_path.replace(".json", "_detail.csv")
    df_out.to_csv(csv_path, index=False)

    # Build summary
    overall_mean = None
    field_means = {f: round(sum(v) / len(v), 4) for f, v in field_sims.items() if v}
    if field_means:
        overall_mean = round(sum(field_means.values()) / len(field_means), 4)

    summary = {
        "model": MODEL,
        "n_evaluated": len(records),
        "field_mean_similarity": field_means,
        "overall_mean_similarity": overall_mean,
    }

    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n=== GROUND TRUTH EVALUATION SUMMARY ===")
    print(f"Model:    {MODEL}")
    print(f"Records evaluated: {summary['n_evaluated']}")

    if summary["n_evaluated"] == 0:
        print("\n  ⚠ No records were successfully evaluated.")
        print("  This is likely because Zenodo is blocking image downloads.")
        print("  See README for how to resolve this.")
    else:
        overall = summary["overall_mean_similarity"]
        print(f"Overall mean similarity: {overall:.3f}")
        print("\nPer-field mean similarity (fuzzy string match, 0–1):")
        for f, s in summary["field_mean_similarity"].items():
            bar = "█" * int(s * 20)
            print(f"  {f:<25} {s:.3f}  {bar}")

    print(f"\nDetailed CSV: {csv_path}")
    print(f"Summary JSON: {output_path}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ground-truth evaluation using GPT-4o")
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--output", type=str, default="gt_eval.json")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--verbose", action="store_true", help="Print per-field comparison for each record")
    args = parser.parse_args()

    run_gt_eval(args.sample, args.output, args.delay, args.verbose)
