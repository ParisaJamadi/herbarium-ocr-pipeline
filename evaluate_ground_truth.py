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
    """Fuzzy string similarity between two values (0–1). Returns None if either is null."""
    if pd.isna(a) or pd.isna(b) or str(a) == "nan" or str(b) == "nan":
        return None
    return SequenceMatcher(None, str(a).lower().strip(), str(b).lower().strip()).ratio()


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
            sim = fuzzy(ext_val, gt_val)
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
