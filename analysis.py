"""
analysis.py — Deep analysis of pipeline results.

Produces a printed report covering:
  1. GT field mapping quality (null rates before/after fix)
  2. Family coverage investigation
  3. Extraction coverage vs GT sparsity comparison
  4. Per-institution accuracy breakdown
  5. Identified gaps and recommendations

Run: python analysis.py
"""

import pandas as pd
import json
import sys
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

XLSX_PATH = "techtest_herbariumdata.xlsx"
RESULTS_CSV = "results.csv"
GT_DETAIL_CSV = "gt_eval_detail.csv"
GT_EVAL_JSON = "gt_eval.json"
COVERAGE_JSON = "coverage_report.json"

SEP = "=" * 65
SEP2 = "-" * 65


def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
df_main = pd.read_excel(XLSX_PATH, sheet_name="main_data")
df_new = pd.read_excel(XLSX_PATH, sheet_name="new_data")
results = pd.read_csv(RESULTS_CSV)
gt_detail = pd.read_csv(GT_DETAIL_CSV)

with open(GT_EVAL_JSON) as f:
    gt_eval = json.load(f)
with open(COVERAGE_JSON) as f:
    coverage = json.load(f)


# ---------------------------------------------------------------------------
# 1. Dataset overview
# ---------------------------------------------------------------------------
section("1. DATASET OVERVIEW")
print(f"  main_data rows : {len(df_main):>5}  columns: {len(df_main.columns)}")
print(f"  new_data rows  : {len(df_new):>5}  columns: {len(df_new.columns)}")
print(f"  results rows   : {len(results):>5}  (extracted new specimens)")
print(f"  gt_detail rows : {len(gt_detail):>5}  (ground-truth evaluation)")

section("2. INSTITUTION BREAKDOWN IN main_data")
inst_counts = df_main["institutionCode"].value_counts(dropna=False)
total = len(df_main)
for inst, count in inst_counts.items():
    fallback = {
        "E":    "NO fallback — RBGE Edinburgh (401)",
        "NHMUK":"GBIF -> NHM portal",
        "K":    "GBIF -> CloudFront (Kew)",
        "L":    "GBIF -> Naturalis (nan in GT)",
        "BR":   "NO fallback — Brussels Meise (403)",
        "B":    "GBIF -> BGBM Berlin",
        "MNHN": "NO fallback — Paris MNHN (403)",
        "P":    "NO fallback — Paris MNHN (403)",
    }
    note = fallback.get(str(inst), "")
    pct = count / total * 100
    print(f"  {str(inst):<8} {count:>4} ({pct:4.1f}%)   {note}")

no_fallback_codes = ["E", "BR", "MNHN", "P"]
no_fallback = df_main[df_main["institutionCode"].isin(no_fallback_codes)]
pct_nf = len(no_fallback) / total * 100
print(f"\n  Specimens with NO institution fallback: {len(no_fallback)} ({pct_nf:.1f}%)")


# ---------------------------------------------------------------------------
# 3. GT column null rates — before/after mapping fix
# ---------------------------------------------------------------------------
section("3. GT FIELD MAPPING — NULL RATES (BUG FIX ANALYSIS)")
print(f"  {'Extracted field':<22} {'OLD GT column':<25} {'OLD null%':>9}   {'NEW GT column':<25} {'NEW null%':>9}")
print(f"  {SEP2}")

old_map = {
    "collector": "verbatimRecordedBy",
    "locality":  "verbatimLocality",
    "elevation": "verbatimElevation",
}
new_map = {
    "collector": "recordedBy",
    "locality":  "locality",
    "elevation": "elevation",
}
for field in ["collector", "locality", "elevation"]:
    old_col = old_map[field]
    new_col = new_map[field]
    old_pct = df_main[old_col].isnull().mean() * 100 if old_col in df_main.columns else 100.0
    new_pct = df_main[new_col].isnull().mean() * 100 if new_col in df_main.columns else 100.0
    improvement = old_pct - new_pct
    print(f"  {field:<22} {old_col:<25} {old_pct:>8.1f}%   {new_col:<25} {new_pct:>8.1f}%  (saves {improvement:.1f}%)")

print(f"\n  These fixes mean {old_map['collector']} (100% null) is replaced by")
print(f"  recordedBy (1.2% null) — collector accuracy can now be measured.")


# ---------------------------------------------------------------------------
# 4. Family coverage investigation
# ---------------------------------------------------------------------------
section("4. FAMILY FIELD INVESTIGATION")

# Coverage in new results
fam_extracted = results["family"].notna().sum()
print(f"  Extraction coverage (results.csv): {fam_extracted}/30 ({fam_extracted/30*100:.0f}%)")
print(f"  Values extracted:")
for v in results["family"].dropna():
    print(f"    {v!r}")

# In GT eval
if "ext_family" in gt_detail.columns:
    ext_fam = gt_detail["ext_family"].notna().sum()
    gt_fam = gt_detail["gt_family"].notna().sum()
    n = len(gt_detail)
    print(f"\n  In GT evaluation ({n} specimens):")
    print(f"    GPT-4o extracted family : {ext_fam}/{n} ({ext_fam/n*100:.0f}%)")
    print(f"    GT family available     : {gt_fam}/{n} ({gt_fam/n*100:.0f}%)")
    print(f"\n  GT family was available but model missed it in {gt_fam - ext_fam} cases")
    print(f"  Extracted families in GT eval:")
    for v in gt_detail["ext_family"].dropna():
        print(f"    {v!r}")

print(f"\n  Root cause: family is a taxonomic classification — it is NOT printed")
print(f"  on most herbarium labels. GPT-4o extracts it only when explicitly stamped.")
print(f"  The updated prompt now asks GPT-4o to INFER family from scientific name.")
print(f"  Expected improvement: coverage should rise from 10% to 70-90%.")


# ---------------------------------------------------------------------------
# 5. Coverage vs GT sparsity comparison
# ---------------------------------------------------------------------------
section("5. COVERAGE vs GT SPARSITY — IS MODEL ACTUALLY DOING WELL?")
print(f"  {'Field':<28} {'Model coverage':>15}  {'GT null%':>9}  {'Verdict'}")
print(f"  {SEP2}")

gt_nulls = {
    "scientific_name":  df_main["scientificName"].isnull().mean() * 100,
    "family":           df_main["family"].isnull().mean() * 100,
    "genus":            df_main["genus"].isnull().mean() * 100,
    "country":          df_main["country"].isnull().mean() * 100,
    "locality":         df_main["locality"].isnull().mean() * 100,
    "elevation":        df_main["elevation"].isnull().mean() * 100,
    "collector":        df_main["recordedBy"].isnull().mean() * 100,
    "type_status":      df_main["typeStatus"].isnull().mean() * 100,
    "institution_code": df_main["institutionCode"].isnull().mean() * 100,
    "habitat":          df_main["habitat"].isnull().mean() * 100,
    "identified_by":    df_main["identifiedBy"].isnull().mean() * 100,
}

field_coverage_pct = coverage.get("field_coverage_overall", {})

for field, gt_null in sorted(gt_nulls.items(), key=lambda x: x[1]):
    model_pct = field_coverage_pct.get(field, 0)
    gt_present = 100 - gt_null
    if model_pct >= gt_present - 10:
        verdict = "OK — matches GT sparsity"
    elif model_pct < gt_present - 30:
        verdict = "UNDER-EXTRACTING vs GT"
    else:
        verdict = "slightly under GT"
    print(f"  {field:<28} {model_pct:>14.1f}%  {gt_null:>8.1f}%  {verdict}")


# ---------------------------------------------------------------------------
# 6. Per-institution accuracy breakdown from GT eval
# ---------------------------------------------------------------------------
section("6. PER-INSTITUTION ACCURACY IN GT EVALUATION")

def extract_institution(occ_id):
    occ = str(occ_id).lower()
    if "bgbm" in occ or "herbarium.bgbm" in occ:
        return "BGBM"
    if "rbge" in occ or "data.rbge" in occ:
        return "RBGE"
    if "specimens.kew" in occ:
        return "KEW"
    if "biodiversitydata.nl" in occ or "naturalis" in occ:
        return "Naturalis"
    if "botanicalcollections.be" in occ:
        return "Brussels"
    if len(str(occ_id)) == 36 and "-" in str(occ_id):
        return "BM (NHM)"
    return "Other"

gt_detail["institution"] = gt_detail["occurrenceID"].apply(extract_institution)
sim_cols = [c for c in gt_detail.columns if c.startswith("sim_")]

inst_scores = {}
for inst, grp in gt_detail.groupby("institution"):
    sims = []
    for col in sim_cols:
        vals = grp[col].dropna().tolist()
        sims.extend(vals)
    if sims:
        inst_scores[inst] = (round(sum(sims) / len(sims), 3), len(grp))

print(f"  {'Institution':<15} {'Avg similarity':>15}  {'Specimens':>10}")
print(f"  {SEP2}")
for inst, (score, n) in sorted(inst_scores.items(), key=lambda x: -x[1][0]):
    print(f"  {inst:<15} {score:>15.3f}  {n:>10}")


# ---------------------------------------------------------------------------
# 7. Summary of gaps and recommendations
# ---------------------------------------------------------------------------
section("7. GAPS & RECOMMENDATIONS")
gaps = [
    ("FIXED",   "collector GT mapped to verbatimRecordedBy (100% null) → now recordedBy (1% null)"),
    ("FIXED",   "locality GT mapped to verbatimLocality (99% null) → now locality (31% null)"),
    ("FIXED",   "elevation GT mapped to verbatimElevation (87% null) → now elevation (78% null)"),
    ("FIXED",   "Prompt updated to infer family from scientific name when not printed"),
    ("GAP",     "identified_by accuracy 0.41 — handwritten names inherently hard; consider name normalisation"),
    ("GAP",     "35% of main_data specimens (RBGE, Brussels, Paris) have no institution fallback"),
    ("GAP",     "family accuracy 0.91 but coverage 10% — post-fix coverage should improve significantly"),
    ("ENHANCE", "Add semantic country normalisation (USA vs United States vs U.S.A.)"),
    ("ENHANCE", "Add taxonomic API lookup (GBIF backbone) to validate/complete scientific_name and family"),
    ("ENHANCE", "Add collection_date parsing quality check — verify collection_date_normalized is valid ISO date"),
]
for tag, note in gaps:
    print(f"  [{tag:<7}] {note}")

print(f"\n{SEP}\n  Run 'python run_pipeline.py --mode eval_gt --gt_sample 20 --verbose'\n"
      f"  to re-evaluate with the fixed GT mappings.\n{SEP}\n")
