"""
Ground-truth evaluation: re-extract a sample of main_data specimens (which have known values)
and measure how accurately GPT-4o's extraction matches the pre-existing metadata.

Usage:
    python evaluate_ground_truth.py --sample 20 --output gt_eval.json
    python evaluate_ground_truth.py --sample 20 --output gt_eval.json --verbose
"""

import openai
import pandas as pd
import requests
import base64
import json
import time
import argparse
import sys
from difflib import SequenceMatcher
from dotenv import load_dotenv

load_dotenv()

XLSX_PATH = "techtest_herbariumdata.xlsx"
MODEL = "gpt-4o"

EXTRACTION_PROMPT = """You are an expert botanist and herbarium curator. Examine this herbarium sheet image carefully.

Extract ALL of the following fields from labels, stamps, handwritten text, and printed text visible on the sheet:

Return a JSON object with EXACTLY these fields (use null for any field not found):
{
  "scientific_name": "full scientific name including author if present",
  "family": "plant family",
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

FIELD_MAP = {
    "scientific_name": "scientificName",
    "family": "family",
    "genus": "genus",
    "country": "country",
    "locality": "verbatimLocality",
    "elevation": "verbatimElevation",
    "collector": "verbatimRecordedBy",
    "type_status": "typeStatus",
    "institution_code": "institutionCode",
    "habitat": "habitat",
    "identified_by": "identifiedBy",
}


def fuzzy(a, b):
    if pd.isna(a) or pd.isna(b) or str(a) == "nan" or str(b) == "nan":
        return None
    return SequenceMatcher(None, str(a).lower().strip(), str(b).lower().strip()).ratio()


def fetch_image_base64(url: str, timeout: int = 30):
    url = url.replace("zenodo.org/record/", "zenodo.org/records/")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://zenodo.org/"
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}", file=sys.stderr)
            return None, None

        content_type = r.headers.get("content-type", "").split(";")[0].strip()
        if not content_type.startswith("image/"):
            print(f"  Not an image (got {content_type})", file=sys.stderr)
            return None, None

        content = r.content
        if len(content) < 100:
            print(f"  Response too small ({len(content)} bytes)", file=sys.stderr)
            return None, None

        return base64.standard_b64encode(content).decode(), content_type

    except Exception as e:
        print(f"  Fetch error: {e}", file=sys.stderr)
        return None, None


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

        img_b64, mtype = fetch_image_base64(row["jpegURL"])
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
            sim = fuzzy(ext_val, gt_val)
            row_result[f"ext_{ext_f}"] = ext_val
            row_result[f"gt_{gt_f}"] = gt_val
            row_result[f"sim_{ext_f}"] = round(sim, 4) if sim is not None else None
            if sim is not None:
                field_sims[ext_f].append(sim)
                sims_this_row.append(sim)

            if verbose:
                flag = "✓" if sim == 1.0 else ("~" if sim and sim > 0.7 else "✗")
                print(f"  {flag} {ext_f}: extracted={ext_val!r}  gt={gt_val!r}  sim={f'{sim:.2f}' if sim is not None else 'N/A'}")

        row_result["confidence"] = extracted.get("confidence")
        row_result["image_quality"] = extracted.get("image_quality")
        records.append(row_result)

        avg_sim = sum(sims_this_row) / len(sims_this_row) if sims_this_row else 0
        print(f"  avg_sim={avg_sim:.2f}  conf={extracted.get('confidence')}")

        if i < len(sample) - 1:
            time.sleep(delay)

    # Save detailed CSV
    df_out = pd.DataFrame(records)
    csv_path = output_path.replace(".json", "_detail.csv")
    df_out.to_csv(csv_path, index=False)

    # Build summary — handle zero records gracefully
    field_mean_sim = {
        f: round(sum(v) / len(v), 4) for f, v in field_sims.items() if v
    }
    overall = round(
        sum(field_mean_sim.values()) / len(field_mean_sim), 4
    ) if field_mean_sim else None

    summary = {
        "model": MODEL,
        "n_evaluated": len(records),
        "field_mean_similarity": field_mean_sim,
        "overall_mean_similarity": overall
    }

    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n=== GROUND TRUTH EVALUATION SUMMARY ===")
    print(f"Model:    {MODEL}")
    print(f"Records evaluated: {summary['n_evaluated']}")

    if overall is not None:
        print(f"Overall mean similarity: {overall:.3f}")
        print("\nPer-field mean similarity (fuzzy string match, 0–1):")
        for f, s in field_mean_sim.items():
            bar = "█" * int(s * 20)
            print(f"  {f:<25} {s:.3f}  {bar}")
    else:
        print("\n  ⚠ No records were successfully evaluated.")
        print("  This is likely because Zenodo is blocking image downloads.")
        print("  See README for how to resolve this.")

    print(f"\nDetailed CSV: {csv_path}")
    print(f"Summary JSON: {output_path}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--output", type=str, default="gt_eval.json")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run_gt_eval(args.sample, args.output, args.delay, args.verbose)
