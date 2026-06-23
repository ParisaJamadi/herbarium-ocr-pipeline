"""
Herbarium Sheet Data Extraction Pipeline
Uses GPT-4o vision to extract structured data from herbarium sheet images.

Usage:
    python extract.py --sample 30 --output results.csv
    python extract.py --sample 50 --output results.csv --delay 2.0
"""

import openai
import pandas as pd
import json
import time
import argparse
import sys
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows consoles (handles arrows, checkmarks, etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from utils import EXTRACTION_PROMPT, fetch_image_base64

load_dotenv()

XLSX_PATH = "techtest_herbariumdata.xlsx"
MODEL = "gpt-4o"


def load_data():
    df_main = pd.read_excel(XLSX_PATH, sheet_name="main_data")
    df_new = pd.read_excel(XLSX_PATH, sheet_name="new_data")
    return df_main, df_new


def extract_from_image(client: openai.OpenAI, image_b64: str, media_type: str, row_meta: dict) -> dict:
    """Send image to GPT-4o and parse extraction result."""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=1500,
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}",
                            "detail": "high"
                        }
                    },
                    {
                        "type": "text",
                        "text": EXTRACTION_PROMPT
                    }
                ]
            }]
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        raw = raw.strip()

        result = json.loads(raw)
        result["index"] = row_meta.get("index")
        result["occurrenceID"] = row_meta.get("occurrenceID")
        result["source_url"] = row_meta.get("jpegURL")
        result["extraction_error"] = None
        return result

    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}", file=sys.stderr)
        return {
            "index": row_meta.get("index"),
            "occurrenceID": row_meta.get("occurrenceID"),
            "source_url": row_meta.get("jpegURL"),
            "extraction_error": f"JSON parse error: {e}"
        }
    except Exception as e:
        print(f"  API error: {e}", file=sys.stderr)
        return {
            "index": row_meta.get("index"),
            "occurrenceID": row_meta.get("occurrenceID"),
            "source_url": row_meta.get("jpegURL"),
            "extraction_error": str(e)
        }


def run_extraction(sample_size: int, output_path: str, delay: float = 1.5):
    client = openai.OpenAI()
    _, df_new = load_data()

    sample = df_new.sample(n=min(sample_size, len(df_new)), random_state=42).reset_index(drop=True)
    print(f"Model: {MODEL}")
    print(f"Processing {len(sample)} specimens from new_data sheet...\n")

    results = []
    for i, row in sample.iterrows():
        url = row["jpegURL"]
        print(f"[{i+1}/{len(sample)}] {row['occurrenceID']}")

        img_b64, media_type = fetch_image_base64(url, occurrence_id=str(row.get("occurrenceID", "")))
        if img_b64 is None:
            results.append({
                "index": row["index"],
                "occurrenceID": row["occurrenceID"],
                "source_url": url,
                "extraction_error": "Image fetch failed"
            })
            continue

        result = extract_from_image(client, img_b64, media_type, row.to_dict())
        results.append(result)
        print(f"  → name={result.get('scientific_name', 'N/A')} | country={result.get('country', 'N/A')} | conf={result.get('confidence', 'N/A')}")

        if i < len(sample) - 1:
            time.sleep(delay)

    df_out = pd.DataFrame(results)
    df_out.to_csv(output_path, index=False)

    errors = df_out["extraction_error"].notna().sum() if "extraction_error" in df_out.columns else 0
    print(f"\n✓ Saved {len(df_out)} records to {output_path}")
    print(f"  Successful extractions: {len(df_out) - errors}")
    print(f"  Failed (image fetch or API error): {errors}")

    if errors == len(df_out):
        print("\n  ⚠ All images failed to download.")
        print("  Zenodo may be blocking automated requests from your network.")
        print("  Try running from a different network or see README for alternatives.")

    return df_out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract herbarium data using GPT-4o Vision")
    parser.add_argument("--sample", type=int, default=30)
    parser.add_argument("--output", type=str, default="results.csv")
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()
    run_extraction(args.sample, args.output, args.delay)
