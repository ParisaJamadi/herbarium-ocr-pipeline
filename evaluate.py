#!/usr/bin/env python3
"""
evaluate.py — Generate coverage + confidence report for extracted herbarium data.

Usage:
  python evaluate.py --results results.csv --output coverage_report.json --verbose
"""

import argparse
import json
import pandas as pd
import sys
from collections import defaultdict

# Fields as defined in the pipeline
EXPECTED_FIELDS = {
    "Taxonomy": ["scientific_name", "family", "genus"],
    "Collection": ["collector", "collection_date", "collection_date_normalized"],
    "Geography": ["locality", "country"],
    "Environment": ["habitat", "elevation"],
    "Institutional": ["institution_code", "barcode", "type_status"],
    "Determination": ["identified_by", "identification_date", "field_notes"],
    "Quality": ["label_language", "image_quality", "confidence"],
}

def flatten_fields():
    """Flatten nested field structure."""
    fields = []
    for category, field_list in EXPECTED_FIELDS.items():
        fields.extend(field_list)
    return fields

def analyze_coverage(results_df, verbose=False):
    """Analyze field coverage and confidence from results."""
    
    all_fields = flatten_fields()
    
    # Filter to only data fields (exclude metadata)
    metadata_cols = {"index", "occurrenceID", "source_url", "extraction_error"}
    data_cols = [col for col in all_fields if col in results_df.columns]
    
    total_records = len(results_df)
    coverage = {}
    confidence_dist = defaultdict(int)
    
    # Calculate coverage per field
    for field in data_cols:
        non_null = results_df[field].notna().sum()
        non_empty = (results_df[field].astype(str).str.strip() != "").sum() if field in results_df.columns else 0
        coverage[field] = {
            "total_records": total_records,
            "non_null_count": int(non_null),
            "coverage_percent": round((non_null / total_records * 100) if total_records > 0 else 0, 2),
            "non_empty_count": int(non_empty),
        }
    
    # Analyze confidence scores if available
    if "confidence" in results_df.columns:
        conf_scores = pd.to_numeric(results_df["confidence"], errors="coerce")
        conf_scores = conf_scores.dropna()
        
        if len(conf_scores) > 0:
            for score in conf_scores:
                # Bin into brackets
                if score >= 0.9:
                    confidence_dist["0.9-1.0"] += 1
                elif score >= 0.7:
                    confidence_dist["0.7-0.9"] += 1
                elif score >= 0.5:
                    confidence_dist["0.5-0.7"] += 1
                else:
                    confidence_dist["0.0-0.5"] += 1
    
    # Organize by category
    coverage_by_category = {}
    for category, fields in EXPECTED_FIELDS.items():
        coverage_by_category[category] = {
            field: coverage.get(field, {"coverage_percent": 0, "non_null_count": 0})
            for field in fields if field in coverage
        }
    
    report = {
        "summary": {
            "total_records": total_records,
            "successful_extractions": int(results_df["extraction_error"].isna().sum()),
            "failed_extractions": int(results_df["extraction_error"].notna().sum()),
        },
        "coverage": coverage_by_category,
        "field_coverage_overall": {
            field: coverage[field]["coverage_percent"]
            for field in data_cols if field in coverage
        },
        "confidence_distribution": dict(confidence_dist) if confidence_dist else {},
    }
    
    return report

def print_report(report, verbose=False):
    """Pretty-print coverage report."""
    
    print("\n" + "=" * 60)
    print("COVERAGE REPORT")
    print("=" * 60)
    
    summary = report["summary"]
    print(f"\nTotal Records: {summary['total_records']}")
    print(f"Successful Extractions: {summary['successful_extractions']}")
    print(f"Failed Extractions: {summary['failed_extractions']}")
    
    if verbose:
        print("\n" + "-" * 60)
        print("COVERAGE BY CATEGORY")
        print("-" * 60)
        
        for category, fields in report["coverage"].items():
            print(f"\n{category}:")
            for field, stats in fields.items():
                coverage_pct = stats.get("coverage_percent", 0)
                count = stats.get("non_null_count", 0)
                print(f"  {field:30s} {coverage_pct:6.1f}% ({count:3d} records)")
    
    if report["confidence_distribution"]:
        print("\n" + "-" * 60)
        print("CONFIDENCE DISTRIBUTION")
        print("-" * 60)
        for bracket, count in sorted(report["confidence_distribution"].items()):
            print(f"  {bracket}: {count}")
    
    print("\n" + "=" * 60)

def main():
    parser = argparse.ArgumentParser(description="Generate coverage report for extracted data")
    parser.add_argument("--results", type=str, default="results.csv",
                        help="Path to results.csv")
    parser.add_argument("--output", type=str, default="coverage_report.json",
                        help="Output JSON file")
    parser.add_argument("--verbose", action="store_true",
                        help="Print detailed coverage breakdown")
    args = parser.parse_args()
    
    try:
        results_df = pd.read_csv(args.results)
    except FileNotFoundError:
        print(f"ERROR: Could not find {args.results}")
        sys.exit(1)
    
    print(f"\nAnalyzing {len(results_df)} records from {args.results}...")
    
    report = analyze_coverage(results_df, verbose=args.verbose)
    
    # Save to JSON
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)
    print(f"✓ Coverage report saved to {args.output}")
    
    # Print summary
    print_report(report, verbose=args.verbose)

if __name__ == "__main__":
    main()
