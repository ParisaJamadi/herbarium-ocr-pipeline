# Herbarium Extraction Pipeline — GPT-4o

Extracts structured data from herbarium sheet images using **GPT-4o** (OpenAI Vision API).

---

## Requirements

```bash
pip install openai pandas openpyxl requests python-dotenv
```

Place the spreadsheet in the same directory as the scripts:
```
techtest_herbariumdata.xlsx
```

Create a `.env` file in the same directory:
```
OPENAI_API_KEY=sk-...
ZENODO_ACCESS_TOKEN=<your-zenodo-token>   # optional — see Troubleshooting
```

**Getting a Zenodo access token** (free):
1. Create an account at [zenodo.org](https://zenodo.org)
2. Go to **Account → Applications → Personal access tokens**
3. Create a token with `deposit:read` scope
4. Add it to `.env` as `ZENODO_ACCESS_TOKEN=...`

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

## Image Source Strategy

The pipeline tries three sources for each specimen image, in order:

1. **Zenodo REST API** — fastest when accessible
2. **Zenodo direct file URL** — fallback within Zenodo
3. **Institution portal** — automatic fallback when Zenodo is blocked

### Institution Portal Coverage

| Institution | Specimens | Status | Image Source |
|---|---|---|---|
| BM / NHM London | UUID occurrenceIDs | ✅ Working | GBIF → `data.nhm.ac.uk` |
| Kew (K) | `specimens.kew.org` | ✅ Working | GBIF → CloudFront CDN |
| BGBM Berlin (B) | `herbarium.bgbm.org` | ✅ Working | GBIF → `image.bgbm.org` |
| Finnish MNH — HA./H. prefix | `id.luomus.fi` | ✅ Working | Finnish portal → `image.laji.fi` |
| Naturalis Leiden (L) | `biodiversitydata.nl` | ✅ Working | GBIF → `medialib.naturalis.nl` |
| RBGE Edinburgh (E) | `data.rbge.org.uk` | ❌ Auth required | IIIF server returns 401 |
| Helsinki EIG. prefix | `id.luomus.fi/EIG.*` | ❌ No media | Finnish portal has no images for EIG records |
| Paris MNHN (P) | `coldb.mnhn.fr` | ❌ Blocked | `mediaphoto.mnhn.fr` returns 403 |
| Meise Brussels (BR) | `botanicalcollections.be` | ❌ Blocked | IIIF image server returns 403 |

**Expected success rate:** ~55–65% of specimens in the test set (RBGE and EIG records are the main gaps).

---

## Changes & Bug Fixes (June 2026)

### Bugs Fixed

| # | File | Issue | Fix |
|---|---|---|---|
| 1 | `evaluate_ground_truth.py` | Wrong xlsx filename (`techtest_herbariumdata_1.xlsx`) — file does not exist | Changed to `techtest_herbariumdata.xlsx` |
| 2 | `evaluate_ground_truth.py` | Had its own `fetch_image_base64` with no Zenodo API fallback, no retries, no URL normalization | Deleted local copy; now imports from `utils.py` |
| 3 | `evaluate_ground_truth.py` | Duplicate `EXTRACTION_PROMPT` (out of sync with `utils.py`) | Deleted local copy; now imports from `utils.py` |
| 4 | `evaluate_ground_truth.py` | Crash (`ValueError: Unknown format code 'f' for NoneType`) when 0 records evaluated | Added None guard before formatting `overall_mean_similarity` |
| 5 | `run_pipeline.py` | Summary message always said "250 new specimens" regardless of `--sample` arg | Changed to use `args.sample` dynamically |
| 6 | `run_pipeline.py` | `─` box-drawing character caused `UnicodeEncodeError` on Windows cp1252 console | Replaced with `-` |
| 7 | `extract.py` | `→` arrow character caused `UnicodeEncodeError` on Windows cp1252 console | Added `sys.stdout.reconfigure(encoding='utf-8')` |

### New Features

| Feature | Files Changed | Description |
|---|---|---|
| Institution portal fallback | `utils.py` | When Zenodo is blocked, automatically tries BM/NHM, Kew, BGBM, Helsinki, and Naturalis portals |
| GBIF-based image lookup | `utils.py` | Uses GBIF occurrence API to resolve institution media URLs (handles BM's UUID→media ID mapping, BGBM's space-padded catalog format, etc.) |
| Zenodo IP-block detection | `utils.py` | Detects "unusual traffic" 403 response body and prints a one-time clear message instead of silently failing |
| UTF-8 console encoding | `extract.py`, `evaluate_ground_truth.py`, `run_pipeline.py` | `sys.stdout/stderr.reconfigure(encoding='utf-8')` + `PYTHONIOENCODING=utf-8` passed to subprocesses — fixes all Unicode errors on Windows |
| occurrence_id passed to fetcher | `extract.py`, `evaluate_ground_truth.py` | `fetch_image_base64()` now receives `occurrence_id` so it can route to the correct institution portal |

---

## What Is Working

- ✅ Full pipeline runs end-to-end without crashing
- ✅ GPT-4o extraction produces structured JSON for all 19 fields
- ✅ Institution fallback automatically rescues BM, Kew, BGBM, Helsinki (HA./H.), and Naturalis specimens
- ✅ Ground-truth evaluation runs and produces similarity scores (overall ~0.64 on test sample)
- ✅ Coverage report with per-category field fill rates and confidence distribution
- ✅ All Unicode characters display correctly on Windows
- ✅ `evaluate_ground_truth.py` loads the correct xlsx file

## What Is Not Working / Known Limitations

- ❌ **RBGE Edinburgh (E) specimens** — `iiif.rbge.org.uk` requires authentication (HTTP 401). No public image API available. Approximately 30–40% of `main_data` specimens are RBGE, so ground-truth scores are based on a biased sub-sample.
- ❌ **Helsinki EIG.* specimens** — the Finnish Luomus portal returns records with `mediaCount: 0` for EIG-prefixed IDs (University of Helsinki herbarium). No image URL can be resolved.
- ❌ **Paris MNHN (P) specimens** — `mediaphoto.mnhn.fr` returns HTTP 403 for automated requests.
- ❌ **Meise Brussels (BR) specimens** — their IIIF image server returns HTTP 403.
- ⚠️ **Zenodo itself is blocked** on this machine/network — the original image source returns 403 for all requests. The institution portal fallback compensates for most (but not all) specimens.
- ⚠️ **`family` field has 0% coverage** — GPT-4o consistently returns `null` for `family`. This is likely because family names are rarely printed on herbarium labels and GPT-4o cannot reliably infer them from the scientific name alone without being explicitly asked.

---

## Troubleshooting

**API key not set:**
```
ERROR: OPENAI_API_KEY environment variable not set.
```
→ Add `OPENAI_API_KEY=sk-...` to your `.env` file (same directory as the scripts).

**Zenodo blocked (`⛔ Zenodo has blocked your IP/network`):**
The pipeline will automatically fall back to institution portals for supported herbaria (BM, Kew, BGBM, Helsinki, Naturalis). For unsupported institutions (RBGE, Paris, Brussels), those specimens will be skipped.

To restore Zenodo access:
1. Try a **VPN** or different network — the block is IP/network-based
2. Add `ZENODO_ACCESS_TOKEN=<token>` to `.env` — tokens sometimes have a separate rate-limit quota
3. Contact Zenodo support: https://zenodo.org/support?category=problem-report

**JSON parse error:**
→ Rare; GPT-4o occasionally wraps output in markdown. The script strips fences automatically.

**UnicodeEncodeError on Windows:**
→ Run with `set PYTHONIOENCODING=utf-8` before executing, or ensure you're using the latest version of the scripts (which set this automatically).
