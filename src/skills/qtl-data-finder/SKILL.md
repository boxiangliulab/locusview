---
name: qtl-data-finder
description: Find QTL datasets (eQTL, sQTL, pQTL, caQTL) for a tissue, cell type or condition — first in the eQTL Catalogue and other QTL databases, then in the literature — resolve and download the summary statistics, and when data is not directly downloadable, draft a request email to the corresponding author. Use when asked to locate QTL data, get sumstats for a tissue, find a dataset behind a paper, or contact authors for unpublished QTL data.
---

# QTL data finder

Works down a ladder — **catalogue → literature → ask a human** — and stops at the first rung that
yields the data. Each rung is cheaper and more reliable than the next, so do not skip ahead.

```bash
S=src/skills/qtl-data-finder/scripts/find_qtl.py

python3 $S search "pancreatic islet" --quant ge --min-n 100   # 1. catalogue
python3 $S resolve QTD000574 --save-metadata sumstats_metadata.jsonl   # 2. URLs + metadata
python3 $S download QTD000574 --out data/qtl                  # 3. fetch
python3 $S papers "pancreatic islet sQTL"                     # 4. literature
python3 $S draft --citation "…" --title "…" --to …            # 5. request email
```

Standard library only — no dependency changes. The catalogue index is cached under
`~/.cache/locusview-qtl-finder/`; pass `--release r8` for the newer table.

## Rung 1 — the eQTL Catalogue

`search` fuzzy-matches the query against tissue, cell type, condition and study labels across 758
datasets (r7) or 1,205 (r8), and ranks by match quality then sample size. Filter with
`--quant` (`ge`, `exon`, `tx`, `txrev`, `leafcutter`, `aptamer`, `microarray`) and `--min-n`.

One study appears as several datasets — the same samples quantified different ways. For splicing
QTLs take `leafcutter`; for expression take `ge`. Do not treat them as independent datasets.

### Resolving files — never build the path by hand

The FTP layout looks deterministic:

```
.../spot/eQTL/sumstats/{study_id}/{dataset_id}/{dataset_id}.all.tsv.gz   nominal + .tbi
.../spot/eQTL/sumstats/{study_id}/{dataset_id}/{dataset_id}.permuted.tsv.gz
.../spot/eQTL/susie/{study_id}/{dataset_id}/{dataset_id}.credible_sets.tsv.gz
```

**But the metadata table lists datasets that are not published yet.** `sumstats/` holds r7 — 42
studies, matching `dataset_metadata_r7.tsv` exactly. r8 is only *partially* out, under
`r8_beta/`, covering 13 studies (QTS000036–41, 46–50, 53, 54). A path built from an r8 row 404s far
more often than not: `QTD000825` is in the r8 table and exists in neither tree. `resolve` HEAD-checks
every URL against both trees and says so plainly when a dataset is listed but unpublished — treat
that answer as "go to rung 2", not as a bug to work around.

`download` is resumable and skips files already complete, so re-running after an interruption is
safe. Nominal sumstats run to gigabytes; fetch `--all-files` only when the permuted and SuSiE
outputs are actually needed.

### The shared metadata store

`--save-metadata` records what a downloaded file cannot state about itself — dataset, QTL type,
biocontext, population, sample size, URL — into the same JSONL that `gwas-catalog-lookup` writes,
so `sumstats-manifest` can fill a row without anyone retyping it:

```bash
python3 $S resolve QTD000574 --save-metadata sumstats_metadata.jsonl
python3 …/manifest.py add-qtl data/QTD000574.all.tsv.gz \
    --dataset PISA --qtl-type eQTL --biocontext pancreatic_islet \
    --metadata sumstats_metadata.jsonl
```

Records are keyed `dataset|qtl_type|biocontext` and upserted, so re-running refreshes them. A
dataset that is listed but unpublished still gets a record (with an empty `download_url`) — the
metadata is valid whether or not the file ever arrives, including when it arrives by email at
rung 3.

Three derivations worth knowing:

- **`qtl_type` comes from `quant_method`, not the study.** `leafcutter` and `txrev` are splicing,
  everything else expression — one study routinely yields both an eQTL and an sQTL record.
- **`population` is blank when it is unknown.** Only 27 of the 42 r7 studies appear in the
  catalogue's `population_assignments.tsv`; the rest print a warning and leave the field empty
  rather than asserting `ALL`. Fill it from the paper before loading. A study gets a single code
  only when one ancestry is ≥ 90% of the sample — GTEx at 705/838 European (84%) is `ALL`.
- **`level_2_context` is populated only for single-cell studies**; bulk tissue leaves it blank.

## Other QTL databases

Not wrapped by the script — check them by hand when the eQTL Catalogue has no match:

| Source | What it has | Access |
|---|---|---|
| **GTEx v8/v10** | 49 tissues, eQTL + sQTL | direct: `storage.googleapis.com/adult-gtex/bulk-qtl/…` (verified) |
| **eQTLGen** | blood, cis + trans, n≈31k | direct download |
| **MetaBrain** | brain regions, cell-type-aware | direct download |
| **DICE / OneK1K** | immune cell types, sc-eQTL | direct download |
| **GTEx individual-level** | genotypes, expression | **dbGaP `phs000424` — controlled, needs an application** |

Controlled-access sources are rung 3 by definition: no script can download them.

## Rung 2 — the literature

`papers` searches Europe PMC and reports, per paper, its accessions (`GSE…`, `E-MTAB-…`,
`EGAS/EGAD…`, `phs…`, `PRJ…`), the `hasData`/open-access flags, full-text links, and any email
addresses. Emails are scraped from **affiliation strings** — that is where PubMed puts the
corresponding author's address; there is no dedicated contact field, so a paper may yield none.

Read the paper's data-availability statement before concluding anything. An accession alone does
not mean summary statistics are public — `phs…` and `EGA…` are controlled access, and many papers
deposit raw reads while keeping QTL sumstats in a supplement or nowhere at all.

## Rung 3 — asking

**`draft` writes a file. It does not send mail, and neither should you.**

Sending is an outward-facing, irreversible action addressed to a named researcher, so a human
decides. There is no SMTP configuration in this repo, and the Gmail MCP server is installed but
unauthenticated — so sending is not merely discouraged here, it is unavailable until the user
authorizes it. Hand back the draft path and let them send it.

```bash
python3 $S draft \
  --to michael.stitzel@jax.org --salutation "Dr. Stitzel" \
  --citation "Kursawe et al. (2025) Annu Rev Genet" \
  --title "…" --reference "doi 10.1146/… · PMID 40803767" \
  --data-kind "islet sQTL summary statistics" \
  --reason "The paper reports islet sQTLs but the deposit (phs001188) is controlled access." \
  --sender "Your name, title, affiliation" \
  --out drafts/stitzel-islet-sqtl.eml
```

The template commits to citing the study, honouring any embargo or licence, and never
redistributing individual-level data. Do not weaken those commitments to make a request more
likely to succeed — locusview has to honour them afterwards.

Fill `--sender` and `--salutation` from the actual user; leaving the `TODO` placeholder in a sent
email is worse than sending nothing. Say explicitly in `--reason` *why* direct download failed —
"controlled access", "link dead", "supplement only" — since that determines what you are asking
for.

## Feeding locusview

Data goes under `data/` (gitignored). Loading into `qtl_datasets` → `qtl_lists` → `qtl_snp_{id}` is
a separate job; this skill stops once the files are on disk. Record the dataset id, release, and
resolved URL alongside them — reproducing a load later needs all three, and the URL alone is
ambiguous across releases.

Never add a test that calls these endpoints: CI is hermetic.
