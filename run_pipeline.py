#!/usr/bin/env python3
"""
run_pipeline.py — Full herbarium extraction + evaluation pipeline (GPT-4o).

Recommended workflow:
  Step 1: python run_pipeline.py --mode extract   --sample 30
  Step 2: python run_pipeline.py --mode eval_gt   --gt_sample 20
  Step 3: python run_pipeline.py --mode report

Or run everything at once:
  python run_pipeline.py --mode all --sample 30 --gt_sample 20

Requirements:
  pip install openai pandas openpyxl requests
  export OPENAI_API_KEY=sk-...
"""

import argparse
import subprocess
import sys
import os
from dotenv import load_dotenv

load_dotenv()

# UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def check_api_key():
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable not set.")
        print("  export OPENAI_API_KEY=sk-...")
        sys.exit(1)


def run(cmd):
    print(f"\n>>> {' '.join(cmd)}\n{'-'*60}")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(cmd, check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description="Herbarium extraction pipeline using GPT-4o")
    parser.add_argument("--mode", choices=["extract", "eval_gt", "report", "all"], default="all",
                        help="Which step(s) to run")
    parser.add_argument("--sample", type=int, default=30,
                        help="Specimens to extract from new_data (default: 30)")
    parser.add_argument("--gt_sample", type=int, default=20,
                        help="Specimens for ground-truth evaluation from main_data (default: 20)")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between API calls (default: 1.5)")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose per-field output in ground-truth eval")
    args = parser.parse_args()

    check_api_key()

    print("=" * 60)
    print("  Herbarium Extraction Pipeline — GPT-4o")
    print("=" * 60)

    if args.mode in ("extract", "all"):
        run([sys.executable, "extract.py",
             "--sample", str(args.sample),
             "--output", "results.csv",
             "--delay", str(args.delay)])

    if args.mode in ("eval_gt", "all"):
        cmd = [sys.executable, "evaluate_ground_truth.py",
               "--sample", str(args.gt_sample),
               "--output", "gt_eval.json",
               "--delay", str(args.delay)]
        if args.verbose:
            cmd.append("--verbose")
        run(cmd)

    if args.mode in ("report", "all"):
        run([sys.executable, "evaluate.py",
             "--results", "results.csv",
             "--output", "coverage_report.json",
             "--verbose"])

    print("\n" + "=" * 60)
    print("✓ Pipeline complete. Output files:")
    print(f"  results.csv           — extracted data for {args.sample} new specimens")
    print("  gt_eval.json          — ground-truth accuracy summary")
    print("  gt_eval_detail.csv    — per-record field comparison vs ground truth")
    print("  coverage_report.json  — field coverage + confidence statistics")
    print("=" * 60)


if __name__ == "__main__":
    main()
