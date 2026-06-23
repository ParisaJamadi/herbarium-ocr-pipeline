# Herbarium Extraction Pipeline — GPT-4o

Extracts structured data from herbarium sheet images using **GPT-4o** (OpenAI Vision API).

## Requirements

```bash
pip install openai pandas openpyxl requests
```

Set your OpenAI API key:
```bash
export OPENAI_API_KEY=sk-...
```

Place the spreadsheet in the same directory:
```
techtest_herbariumdata_1.xlsx
```

---

## Quick Start

Run the full pipeline (extract 30 new specimens + evaluate on 20 ground-truth specimens):

```bash
python run_pipeline.py --mode all --sample 30 --gt_sample 20
```

---

## Individual Steps

**Step 1 — Extract new specimens** (`new_data` sheet, no pre-existing metadata):
```bash
python extract.py --sample 30 --output results.csv
```

**Step 2 — Ground-truth evaluation** (re-extract `main_data` specimens with known values):
```bash
python evaluate_ground_truth.py --sample 20 --output gt_eval.json --verbose
```

**Step 3 — Coverage report** on extracted new data:
```bash
python evaluate.py --results results.csv --output coverage_report.json --verbose
```

---

## Output Files

| File | Description |
|---|---|
| `results.csv` | Extracted data for new_data specimens |
| `gt_eval.json` | Per-field fuzzy similarity scores vs ground truth |
| `gt_eval_detail.csv` | Row-level field comparison vs ground truth |
| `coverage_report.json` | Field coverage + confidence distribution |

---

## Extracted Fields (19 total)

| Category | Fields |
|---|---|
| Taxonomy | `scientific_name`, `family`, `genus` |
| Collection | `collector`, `collection_date`, `collection_date_normalized` |
| Geography | `locality`, `country` |
| Environment | `habitat`, `elevation` |
| Institutional | `institution_code`, `barcode`, `type_status` |
| Determination | `identified_by`, `identification_date`, `field_notes` |
| Quality | `label_language`, `image_quality`, `confidence` |

---

## Model

**GPT-4o** with `"detail": "high"` image setting — uses full image resolution for maximum label legibility.

---

## Rate Limiting & Cost

- Default delay: 1.5 seconds between calls (adjust with `--delay`)
- Approximate cost: ~$0.01–0.02 per image at high detail = **~$0.30–0.60 for 30 specimens**
- For all 250 specimens: ~$2.50–5.00

---

## Troubleshooting

**API key not set:**
```
ERROR: OPENAI_API_KEY environment variable not set.
```
→ Run `export OPENAI_API_KEY=sk-...` first

**Image fetch failed:**
→ The Zenodo image URLs require internet access. Make sure you're not behind a restrictive firewall.

**JSON parse error:**
→ Rare; GPT-4o occasionally wraps output in markdown. The script strips fences automatically.
