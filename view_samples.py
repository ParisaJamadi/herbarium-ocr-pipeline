"""
Quick viewer — downloads a few specimen images and opens them.
Run: python view_samples.py --sheet new_data --n 5
"""
import argparse
import os
import sys
import subprocess
import pandas as pd
from dotenv import load_dotenv
from utils import fetch_image_base64
import base64

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

XLSX_PATH = "techtest_herbariumdata.xlsx"

parser = argparse.ArgumentParser()
parser.add_argument("--sheet", default="new_data", choices=["new_data", "main_data"])
parser.add_argument("--n", type=int, default=3, help="Number of images to download")
parser.add_argument("--open", action="store_true", help="Open images in viewer after saving (default: save only)")
args = parser.parse_args()

df = pd.read_excel(XLSX_PATH, sheet_name=args.sheet)
sample = df.dropna(subset=["jpegURL"]).head(args.n)

os.makedirs("sample_images", exist_ok=True)

for i, row in sample.iterrows():
    occ = str(row.get("occurrenceID", f"specimen_{i}"))
    url = row["jpegURL"]
    name = str(row.get("scientificName", "unknown")) if args.sheet == "main_data" else "unknown"

    print(f"[{i+1}] {occ}")
    print(f"     URL: {url}")
    if name != "unknown":
        print(f"     Name: {name}")

    b64, ct = fetch_image_base64(url, occurrence_id=occ)
    if b64 is None:
        print("     FAILED to download image\n")
        continue

    # Save as JPEG
    safe_name = occ.replace("/", "_").replace(":", "_").replace("?", "_")[-40:]
    ext = "jpg" if "jpeg" in ct else ct.split("/")[-1]
    filepath = f"sample_images/{safe_name}.{ext}"
    with open(filepath, "wb") as f:
        f.write(base64.b64decode(b64))

    size_kb = os.path.getsize(filepath) // 1024
    print(f"     Saved: {filepath} ({size_kb} KB)")

    if args.open:
        # Open with default image viewer (Windows needs absolute path)
        if sys.platform == "win32":
            os.startfile(os.path.abspath(filepath))
        elif sys.platform == "darwin":
            subprocess.run(["open", filepath])
        else:
            subprocess.run(["xdg-open", filepath])
    print()

print(f"Done. Images saved to: sample_images/")
