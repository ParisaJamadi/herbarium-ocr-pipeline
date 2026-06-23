# Herbarium Extraction Pipeline — GPT-4o

Extracts structured data from herbarium sheet images using **GPT-4o** (OpenAI Vision API).

---

## Project Architecture

```
files/
├── .env                        # API keys (never commit this)
├── techtest_herbariumdata.xlsx # Input data (2 sheets: main_data, new_data)
│
├── utils.py                    # Shared: image fetching, Zenodo auth, institution fallbacks
├── extract.py                  # Step 1: extract data from new_data specimens
├── evaluate_ground_truth.py    # Step 2: accuracy check against known main_data values
├── evaluate.py                 # Step 3: field coverage + confidence report
├── run_pipeline.py             # Orchestrator: runs all 3 steps in sequence
│
├── results.csv                 # OUTPUT: extracted fields for new specimens
├── gt_eval.json                # OUTPUT: per-field accuracy scores
├── gt_eval_detail.csv          # OUTPUT: row-level comparison vs ground truth
└── coverage_report.json        # OUTPUT: field coverage statistics
```

---

## Setup

```bash
pip install openai pandas openpyxl requests python-dotenv
```

Create a `.env` file in the same directory:
```
OPENAI_API_KEY=sk-...
ZENODO_ACCESS_TOKEN=<your-zenodo-token>
```

**Getting a Zenodo access token** (required — dataset is access-restricted):
1. Create a free account at [zenodo.org](https://zenodo.org)
2. Go to **Account → Applications → Personal access tokens**
3. Click **New token**, leave all scopes unchecked, click **Create**
4. Copy the token into `.env`

---

## Quick Start

```bash
python run_pipeline.py --mode all --sample 30 --gt_sample 20
```

### Individual steps

```bash
# Step 1 only — extract new specimens
python extract.py --sample 30 --output results.csv

# Step 2 only — ground-truth accuracy check
python evaluate_ground_truth.py --sample 20 --output gt_eval.json --verbose

# Step 3 only — coverage report on existing results
python evaluate.py --results results.csv --output coverage_report.json --verbose
```

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

## Output Files

| File | Description |
|---|---|
| `results.csv` | All 19 extracted fields for each new specimen |
| `gt_eval.json` | Mean fuzzy similarity score per field vs ground truth |
| `gt_eval_detail.csv` | Side-by-side extracted vs ground truth for each record |
| `coverage_report.json` | % of records where each field was filled |

---

## Model

**GPT-4o** with `"detail": "high"` — uses full image resolution for maximum label legibility. Temperature set to 0 for deterministic output.

---

## Rate Limiting & Cost

- Default delay: 1.5 seconds between calls (adjust with `--delay`)
- ~$0.01–0.02 per image = **~$0.30–0.60 for 30 specimens**
- For all 250 specimens: ~$2.50–5.00

---

## Results (30 specimens, June 2026)

### Extraction
- **30/30 successful** — 100% success rate
- All 30 returned `confidence: high`

### Ground Truth Accuracy (20 specimens, overall: **0.776**)

| Field | Score | Notes |
|---|---|---|
| `genus` | 0.911 | Near-perfect |
| `family` | 0.910 | Very strong |
| `country` | 0.843 | Minor name variants |
| `elevation` | 0.828 | Unit/format differences |
| `type_status` | 0.801 | Clear labels |
| `habitat` | 0.786 | Free text variation |
| `scientific_name` | 0.772 | Author citation differences |
| `institution_code` | 0.722 | Some ambiguous labels |
| `identified_by` | 0.409 | Handwritten, often partial |

### Field Coverage (30 new specimens)

| Field | Coverage |
|---|---|
| scientific_name, genus, collector, locality, institution_code, barcode, label_language, image_quality, confidence | **100%** |
| country | 90% |
| collection_date | 87% |
| identified_by | 70% |
| field_notes | 67% |
| identification_date | 60% |
| habitat | 50% |
| elevation | 47% |
| type_status | 23% |
| family | 10% |

---

## Troubleshooting

**API key not set:**
→ Add `OPENAI_API_KEY=sk-...` to `.env`

**Zenodo 403 with token:**
→ Make sure the token is saved in `.env` as `ZENODO_ACCESS_TOKEN=...`
→ Do NOT send the token with a browser User-Agent — the code handles this automatically

**JSON parse error:**
→ Rare; GPT-4o occasionally wraps output in markdown fences. The script strips them automatically.

**UnicodeEncodeError on Windows:**
→ Run with `set PYTHONIOENCODING=utf-8` or use the latest scripts (which set this automatically)

---

## Changes Log (June 2026)

| Fix | File |
|---|---|
| Wrong xlsx filename in ground-truth script | `evaluate_ground_truth.py` |
| Duplicate `fetch_image_base64` without Zenodo fallback | `evaluate_ground_truth.py` |
| Crash on 0 evaluated records (None format error) | `evaluate_ground_truth.py` |
| Zenodo API blocked by browser User-Agent even with token | `utils.py` |
| Zenodo duplicate `Content-Type` header breaking GPT-4o data URL | `utils.py` |
| Institution portal fallback (BM, Kew, BGBM, Helsinki, Naturalis) | `utils.py` |
| Hardcoded "250 specimens" in pipeline summary | `run_pipeline.py` |
| UnicodeEncodeError on Windows cp1252 console | all scripts |
