---
name: gwas-catalog-lookup
description: Find the largest-sample GWAS Catalog study for a trait name and return its accession, summary-statistics download URLs, and metadata YAML. Use when asked to locate a GWAS for a trait, pick the best-powered study among similar trait names, find a GCST accession, or get FTP/harmonised sumstats links for ingestion into locusview.
---

# GWAS Catalog lookup

Turns a free-text trait name into: the best-powered study for that trait, its `GCST` accession,
FTP download URLs for the summary statistics, and the metadata YAML that ships beside them.

## Use the script

```bash
python3 src/skills/gwas-catalog-lookup/scripts/find_gwas.py "basophil count"
```

Standard library only — no `uv sync`, no added dependencies. A run takes 15–30 s (several paged
API calls). Useful flags:

| Flag | Effect |
|---|---|
| `--top N` | how many candidates to list (default 10) |
| `--ancestry european` | keep studies whose discovery sample **includes** that ancestry group |
| `--any-sumstats` | keep studies with no summary statistics (default: require them) |
| `--loose` | skip the relevance filter — use when a correct trait was wrongly dropped |
| `--json` | machine-readable output, for piping into ingestion code |
| `--save-yaml DIR` | download the winner's metadata YAML into `DIR` |
| `--save-metadata FILE` | upsert the winner into the shared metadata store |

Report back the accession, the sample size, and the download URLs. Show the candidate table when
the top two are close in N — picking between them is the user's call, not yours.

## How it resolves a trait name

Trait matching is the hard part, and the obvious approaches are all wrong in ways that are easy to
miss because they still return plausible-looking studies.

1. **Exact reported-trait lookup.** `studies/search/findByDiseaseTrait` is an exact,
   case-insensitive match on the author-declared trait. Precise but not fuzzy — `basophil` returns
   nothing, `basophil count` returns 19 studies.
2. **Vocabulary discovery.** The Solr index (`/gwas/api/search?fq=resourcename:trait`) returns EFO
   terms carrying both `synonyms` and `reportedTrait[]` — the full list of author strings mapped to
   that term. That list is where near-miss names live: `Basophill count (UKB data field 30160)`,
   `Absolute basophil count`, `White blood cell count (basophil)`.
3. **Relevance filter, per string.** Every candidate name is scored against the query on its own,
   then the survivors are looked up exactly.
4. **Rank by discovery N**, summing only `type == "initial"` ancestry rows.

### Traps this already handles — do not "simplify" them away

- **Solr ranking cannot be trusted for the exact term.** Searching `mean corpuscular volume` does
  not return the `EFO_0004526` term in the top 50 hits; it returns publications and sibling traits.
  This is why the exact `findByDiseaseTrait` path runs in parallel rather than as a fallback.
- **Whole-string similarity leaks sibling traits.** `basophil count` vs `eosinophil count` scores
  0.80 — above any cutoff loose enough to tolerate plurals. Matching is per-token, where
  `basophil`/`eosinophil` scores 0.67 and is rejected while `basophil`/`basophils` scores 0.94 and
  is kept.
- **"Generic" words are not generic in hematology.** *volume*, *concentration*, *percentage* and
  *width* are exactly what separate MCV from MCH from MCHC. Only structural stopwords
  (`of`, `the`, `and`…) are ignored.
- **Broad parent terms hand back the wrong trait.** `myeloid leukocyte count` carries hundreds of
  studies, so letting it through makes `basophil count` return the largest *white blood cell count*
  study. Dropped terms are printed so a real miss is visible.
- **`studies/search/findByEfoTrait` returns 0 for every label tried** — it looks usable and is not.
  Use `findByEfoUri` with the full `http://www.ebi.ac.uk/efo/EFO_…` URI instead.

## Download URLs

FTP layout, for accession `GCST90002296`:

```
.../summary_statistics/GCST90002001-GCST90003000/GCST90002296/
    GCST90002296_buildGRCh37.tsv.gz            raw, author-submitted
    GCST90002296_buildGRCh37.tsv.gz-meta.yaml  metadata for the raw file
    md5sum.txt
    harmonised/
        32888493-GCST90002296-EFO_0005090.h.tsv.gz            harmonised
        32888493-GCST90002296-EFO_0005090.h.tsv.gz-meta.yaml  metadata for it
```

The bucket directory is the accession's number rounded down to a block of 1000
(`GCST{lo:06d}-GCST{lo+999:06d}`).

**Never construct the filenames.** Harmonised files appear both as `{accession}.h.tsv.gz` and as
the older `{pmid}-{accession}-{efo}.h.tsv.gz`, and raw files carry a build suffix that varies. The
script lists the directory instead. Prefer the **harmonised** file for anything that needs
consistent alleles and coordinates.

`fullPvalueSet: false` on the study means no summary statistics exist — the FTP directory will 404.

## The metadata YAML

Every sumstats file has a sibling `*-meta.yaml` giving genome build, sample sizes, ancestries, file
type, and md5:

```yaml
gwas_id: GCST90002379
genome_assembly: GRCh37
samples:
  - sample_ancestry_category: [European]
    sample_ancestry: [British]
    sample_size: 408112
data_file_name: GCST90002379_buildGRCh37.tsv
data_file_md5sum: 9849b1b3ddfec7aff277a2e9932e792f
is_harmonised: false
```

**The `samples` list often repeats the same block several times.** Do not sum `sample_size` across
entries — take the max, or read N from the REST API's ancestry rows instead.

Read `genome_assembly` before ingesting: raw files are frequently GRCh37 while the harmonised file
is GRCh38.

## The shared metadata store

`--save-metadata sumstats_metadata.jsonl` records what a downloaded data file cannot state about
itself — accession, trait, population, sample size, URL — so the `sumstats-manifest` skill fills a
manifest row without anyone retyping it:

```bash
python3 …/find_gwas.py "basophil count" --save-metadata sumstats_metadata.jsonl
python3 …/manifest.py add-gwas data/GCST90002296.tsv.gz \
    --accession GCST90002296 --metadata sumstats_metadata.jsonl
```

One JSONL record per study, upserted on `kind` + `key` so re-running refreshes rather than
duplicates. `qtl-data-finder` writes into the same file with `kind: "qtl"`.

Two fields are guesses and are labelled as such in `provenance`:

- **`trait`** is the *reported* trait with non-alphanumerics underscored (`Basophil_count`). The
  original string is kept in `provenance.reported_trait`.
- **`type`** always defaults to `quant`. The API does not distinguish quantitative from
  case/control, so set `--type cc` on the manifest step for a binary trait.

`population` is a single code only when the discovery sample is one ancestral group; a
trans-ancestry study is `ALL` even when one group dominates. `sample_size` sums the `initial`
ancestry rows and excludes replication.

## Feeding locusview

`GwasDataset` (`src/backend/locusview/requestinfo.py`) is `(id, trait, population, source,
accession)` — the accession and the reported trait come straight from this lookup, and `population`
maps from the discovery ancestry. Loading into the `gwas_datasets` → `gwas_lists` → `gwas_snp_{id}`
tables is a separate job; this skill stops at identifying the study and its files.

Keep downloaded data under `data/` — it is gitignored, and CI must stay hermetic, so never add a
test that calls these endpoints.
