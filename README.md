# Herbarium Extraction Pipeline — GPT-4o

Extracts structured metadata from scanned herbarium sheet images using **GPT-4o Vision API**.  
Handles image retrieval from Zenodo with institution-specific fallbacks, and evaluates extraction
accuracy against a ground-truth dataset using field-aware fuzzy matching.

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
├── analysis.py                 # Standalone deep-analysis report (run any time)
│
├── results.csv                 # OUTPUT: extracted fields for new specimens
├── gt_eval.json                # OUTPUT: per-field accuracy scores
├── gt_eval_detail.csv          # OUTPUT: row-level comparison vs ground truth
└── coverage_report.json        # OUTPUT: field coverage statistics
```

---

## Input Data

`techtest_herbariumdata.xlsx` has two sheets:

| Sheet | Rows | Purpose |
|---|---|---|
| `main_data` | 500 | Known ground-truth metadata — used for accuracy evaluation |
| `new_data` | 250 | New specimens with no metadata — the pipeline extracts these |

`new_data` contains only: `index`, `DOI`, `jpegURL`, `jsonURL`, `occurrenceID`.  
The pipeline downloads images via `jpegURL` and uses `occurrenceID` to route institution fallbacks.

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
# Run the full pipeline (extract 30 new specimens + evaluate 20 GT specimens)
python run_pipeline.py --mode all --sample 30 --gt_sample 20

# Run analysis report on existing output files
python analysis.py
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

## Image Fetching Strategy

Zenodo (primary image host) blocks automated downloads. The pipeline uses a layered fallback:

1. **Zenodo REST API** with `ZENODO_ACCESS_TOKEN` — uses plain `requests.get` (not a browser User-Agent) to avoid bot detection
2. **Zenodo direct URL** — retry with exponential backoff
3. **Institution portal fallback** — parsed from `occurrenceID`:

| Institution | Code | Fallback |
|---|---|---|
| RBGE Edinburgh | `E` | None — Zenodo only (401 on direct portal) |
| NHM London | `NHMUK` | GBIF → NHM portal |
| Kew Gardens | `K` | GBIF → CloudFront CDN |
| Naturalis | `L` | GBIF → Naturalis portal |
| BGBM Berlin | `B` | GBIF (barcode reformatted: `B100003484` → `B 10 0003484`) |
| Brussels Meise | `BR` | None — Zenodo only (403 on direct portal) |
| Paris MNHN | `MNHN` | None — Zenodo only (403 on direct portal) |

**35% of `main_data` specimens (RBGE 146 + Brussels 24 + Paris 6 = 176) have no institution fallback** — they require a working Zenodo connection.

---

## Output Files

| File | Description |
|---|---|
| `results.csv` | All 19 extracted fields for each new specimen |
| `gt_eval.json` | Mean fuzzy similarity score per field vs ground truth |
| `gt_eval_detail.csv` | Side-by-side extracted vs ground truth for each record |
| `coverage_report.json` | % of records where each field was filled |

---

## Ground-Truth Evaluation — How It Works

`evaluate_ground_truth.py` re-extracts a sample of `main_data` specimens (which have known values) and compares GPT-4o's output against the ground truth using **field-aware fuzzy matching**:

| Field | Normalisation applied before comparison |
|---|---|
| `elevation` | Strip units (m/ft), convert feet → metres, handle ranges (e.g. "0–30 m" → 15) |
| `scientific_name` | Take only genus + species epithet, drop author citation (e.g. "L.", "Sm.") |
| `institution_code` | Map known aliases: `RBGE`→`E`, `NHM`→`NHMUK`, `Kew`→`K`, `Naturalis`→`L` |
| `collector` | Strip punctuation, sort name tokens (handles "Smith, J." vs "J. Smith") |
| `family` | Prompt instructs GPT-4o to infer family from scientific name when not on label |
| All others | Lowercase + strip whitespace |

**GT column mapping** (uses the best-populated GT columns):

| Extracted field | GT column used | GT null% |
|---|---|---|
| `collector` | `recordedBy` | 1% |
| `locality` | `locality` | 31% |
| `elevation` | `elevation` | 78% |

---

## Model

**GPT-4o** with `"detail": "high"` — full image resolution for maximum label legibility.  
Temperature set to 0 for deterministic output.

---

## Rate Limiting & Cost

- Default delay: 1.5 seconds between calls (adjust with `--delay`)
- ~$0.01–0.02 per image = **~$0.30–0.60 for 30 specimens**
- For all 250 specimens: ~$2.50–5.00

---

## Results (30 specimens, June 2026)

### Extraction Coverage (30 new specimens)

| Field | Coverage | Notes |
|---|---|---|
| scientific_name, genus, collector, locality, institution_code, barcode, label_language, image_quality, confidence | **100%** | Always found |
| country | 90% | 3 missing |
| collection_date | 87% | |
| identified_by | 70% | |
| field_notes | 67% | |
| identification_date | 60% | |
| habitat | 50% | Sparse on old labels — expected |
| elevation | 47% | Sparse on old labels — expected |
| type_status | 23% | Correct — only ~29% of specimens are type specimens |
| family | ~70–90%* | *After prompt fix to infer from scientific name |

### Ground Truth Accuracy (20 specimens, June 2026)

With field-aware normalisation applied (see above):

| Field | Score | Grade | Notes |
|---|---|---|---|
| `family` | 0.976 | Excellent | Inferred from scientific name |
| `genus` | 0.911 | Excellent | |
| `country` | 0.803 | Good | |
| `type_status` | 0.801 | Good | |
| `scientific_name` | 0.783 | Good | After stripping author citation |
| `habitat` | 0.669 | Fair | Free-text variation |
| `institution_code` | 0.675 | Fair | After alias normalisation |
| `collector` | 0.633 | Fair | Handwritten names, varied formats |
| `locality` | 0.582 | Fair | Free-text, highly variable |
| `elevation` | 0.419 | Acceptable | After unit/feet conversion fix |
| `identified_by` | 0.399 | Acceptable | Handwritten determiners — inherently hard |
| **Overall** | **0.696** | **Good** | Honest score — all fields now measured |

> The previous overall of 0.776 was inflated because `collector` and `locality` were mapped to GT
> columns that were 100% / 99% null, so those comparisons were silently skipped.

---

## Troubleshooting

**Zenodo 403 with token:**  
→ Add `ZENODO_ACCESS_TOKEN=...` to `.env`  
→ Do NOT send the token with a browser User-Agent — the code handles this automatically

**0 records evaluated in GT eval:**  
→ Zenodo is blocking image downloads. Try a different network or mobile hotspot.  
→ Specimens from RBGE (29%), Brussels (5%), and Paris (1%) have no institution fallback.

**JSON parse error:**  
→ GPT-4o occasionally wraps output in markdown fences — the scripts strip these automatically.

**UnicodeEncodeError on Windows:**  
→ Run with `set PYTHONIOENCODING=utf-8` or use the latest scripts (which configure this at startup).

---

## Changes Log (June 2026)

| Fix | File |
|---|---|
| Wrong xlsx filename (`_1` suffix) in GT script | `evaluate_ground_truth.py` |
| Duplicate `fetch_image_base64` without Zenodo fallback | `evaluate_ground_truth.py` |
| Crash when 0 records evaluated (None format error) | `evaluate_ground_truth.py` |
| GT field mapping: `collector`→`verbatimRecordedBy` (100% null) fixed to `recordedBy` | `evaluate_ground_truth.py` |
| GT field mapping: `locality`→`verbatimLocality` (99% null) fixed to `locality` | `evaluate_ground_truth.py` |
| GT field mapping: `elevation`→`verbatimElevation` fixed to `elevation` | `evaluate_ground_truth.py` |
| Field-aware normalisation: elevation units, scientific name, institution aliases, collector format | `evaluate_ground_truth.py` |
| Zenodo API blocked by browser User-Agent even with token | `utils.py` |
| Zenodo duplicate `Content-Type` header breaking GPT-4o data URL | `utils.py` |
| Prompt updated to infer `family` from scientific name when not printed on label | `utils.py` |
| Institution portal fallback (BM, Kew, BGBM, Helsinki, Naturalis) | `utils.py` |
| Hardcoded "250 specimens" in pipeline summary | `run_pipeline.py` |
| UnicodeEncodeError on Windows cp1252 console | all scripts |
