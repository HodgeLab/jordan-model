#!/bin/bash
# run_pipeline.sh — runs the Jordan-model pipeline in dependency order.
# Usage:  bash run_pipeline.sh [--skip-fetch]
#   --skip-fetch : reuse existing profile CSVs (saves API calls; checks they exist)
set -e

need() { [ -f "$1" ] || { echo "MISSING: $1 — run the step that produces it"; exit 1; }; }
newer() { if [ "$1" -ot "$2" ]; then echo "STALE: $1 is older than $2 — regenerate it"; exit 1; fi; }

if [ "$1" != "--skip-fetch" ]; then
  echo "=== 1/5 RE profiles (NSRDB + Renewables.ninja; needs API keys in env) ==="
  python re_profiles_2018.py
else
  echo "=== 1/5 skipped (reusing existing profiles) ==="
fi
need solar_2018_hourly.csv; need wind_2018_hourly.csv; need temp_2018_hourly.csv

echo "=== 2/5 load model ==="
python load_model.py
need load_2018_hourly.csv
newer load_2018_hourly.csv temp_2018_hourly.csv

echo "=== 3/5 annual PCM ==="
python annual_pcm_v2.py

echo "=== 4/5 network build + snapshot studies + export ==="
python jordan_n1_fixed.py
need jordan_net.json

echo "=== 5/5 Birchfield structural metrics ==="
python birchfield_metrics.py jordan_net.json

echo ""
echo "PIPELINE COMPLETE. Deliverables:"
echo "  re_fleet_2018_report.txt | annual_energy_mix.csv | annual_dispatch.csv | birchfield_table.csv"