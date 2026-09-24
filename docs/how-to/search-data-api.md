# How to query the Search data API from Python

The **Search data** tab (`/search-data`) has a JSON twin at **`/api/search-data`** that runs
exactly the same search, so scripts can fetch per-context QTL/GWAS association results directly.
It is served by `src/backend/locusview/routers/search_data.py` (see `_to_json` for the full
response shape); the interactive parameter reference is at `/docs` on any running instance.

## Parameters

| Parameter  | Required | Meaning |
|------------|----------|---------|
| `q`        | yes      | A gene symbol (`TP53`), Ensembl gene id (`ENSG00000141510`), rsID (`rs1042522`), or position (`chr17:7676154`). |
| `p`        | no       | p-value threshold — only associations with `p < p` are returned. Default `1e-4`; any number in `(0, 1]` (`1` returns everything). |
| `datasets` | no       | Limit the search to specific datasets: comma-separated `qtl:<id>` / `gwas:<id>` keys (the Data Browser's own keys). Default: every dataset. |

## Example

```python
import requests
import pandas as pd

BASE = "http://127.0.0.1:8000"  # your locusview instance

r = requests.get(f"{BASE}/api/search-data", params={"q": "TP53", "p": 1e-4}, timeout=60)
r.raise_for_status()
data = r.json()

print(data["type"], data["n_contexts"], "contexts,", data["n_rows"], "rows")

# The same table as the Search data page, row for row:
df = pd.DataFrame(data["rows"])
```

## Response

A completed search returns HTTP 200 (even when nothing passes the threshold). `rows` is exactly
the Search data page's table — same rows, same order, same columns (built by `_table_rows`, which
the page's table mirrors; `tests/test_search_data.py` checks the two cell by cell):

```json
{
  "query": "TP53",
  "type": "gene",
  "p_threshold": 0.0001,
  "gene": {"symbol": "TP53", "ensembl_id": "ENSG00000141510.18", "chrom": "17", "start": 7661779, "end": 7687538},
  "variant": null,
  "datasets_searched": 147,
  "datasets_failed": 0,
  "n_contexts": 54,
  "n_rows": 78,
  "rows": [
    {"context": "Blood", "dataset": "eQTL-Catalogue / INTERVAL", "type": "eQTL",
     "phenotype": "ENSG00000141510", "lead_snp": "rs78378222", "variant": "chr17:7668434 G>T",
     "pvalue": 2.29658e-92, "beta": -0.70527}
  ]
}
```

- **Gene searches** (`type: "gene"`, QTL only — GWAS has no gene concept) have columns
  `context, dataset, type, phenotype, lead_snp, variant, pvalue, beta`: each of the gene's
  phenotypes with its most significant SNP.
- **Variant searches** (`type: "variant"`, QTL and GWAS) have columns
  `context, dataset, type, phenotype, pvalue, beta`: each phenotype tested at the variant
  (`phenotype` is `null` for GWAS rows). `variant` gives the resolved position (and `rsid` when
  you searched one).
- p-values and β are full precision; the page only rounds them for display.
- `datasets_failed` counts datasets that could not be searched in time (they are missing from
  `rows`); retrying usually succeeds.

Errors return `{"query": ..., "error": "<message>"}` with **400** (missing `q`, invalid `p`,
unrecognized query, or a region — use the Data Browser for regions) or **404** (unknown gene/rsID).
