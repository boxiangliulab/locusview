#!/usr/bin/env bash
# Smoke test: prove the genomics runtime works end to end.
#
# It creates a tiny BED-like file, compresses it with bgzip, indexes it with
# tabix, and queries a region — the exact round-trip our Phase-1 ingest relies
# on. If the genomics toolchain (HTSlib: bgzip/tabix, plus bcftools) is missing
# or broken, this fails loudly here instead of halfway through a feature.
#
# Run locally:  bash scripts/smoke_tabix.sh
set -euo pipefail

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

bed="$tmp/toy.bed"
# BED is 0-based, half-open: chrom  start  end  name
printf '1\t100\t200\tfeatA\n1\t500\t600\tfeatB\n2\t100\t200\tfeatC\n' > "$bed"

bgzip "$bed"                 # -> toy.bed.gz
tabix -p bed "$bed.gz"       # -> toy.bed.gz.tbi

# tabix regions are 1-based, closed. 1:150-160 overlaps featA (BED 100-200).
result="$(tabix "$bed.gz" 1:150-160)"
echo "tabix 1:150-160 ->"
echo "${result:-（no rows）}"

if ! grep -q "featA" <<< "$result"; then
  echo "SMOKE TEST FAILED: expected featA in region 1:150-160" >&2
  exit 1
fi
if grep -q "featC" <<< "$result"; then
  echo "SMOKE TEST FAILED: featC (chr2) must not appear in a chr1 query" >&2
  exit 1
fi

echo "bcftools: $(bcftools --version | head -1)"
echo "SMOKE TEST PASSED — genomics runtime (bgzip/tabix/bcftools) is working."
