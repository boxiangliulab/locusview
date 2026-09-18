---
name: sumstats-manifest
description: Read the first lines of every downloaded QTL summary-statistics file, work out its delimiter and which column is chrom/position/ref/alt/beta/pval, and fill that layout back into the qtlliteraturereview table; then register the files in qtl_manifest.tsv / gwas_manifest.tsv with their provenance and validate them. Use after download-qtl, to build or update a manifest, to work out which column is beta/pval/chrom in a file, or to check that an existing manifest still matches the files on disk.
---

# Summary-statistics manifest — stage 4 of 4

Two jobs, in order:

1. **`fill-table`** — read the head of every file `download-qtl` fetched and record its layout in
   the review table, so the table says what each file actually contains.
2. **`add-qtl` / `add-gwas` / `validate`** — promote those files into `qtl_manifest.tsv` /
   `gwas_manifest.tsv` with the provenance a data file cannot state about itself.

Both rest on the same idea: a manifest row comes from two inputs that each know half the answer:

- **the file** supplies the *layout* — delimiter and which column is chrom, beta, pval…
- **the shared metadata store** supplies the *provenance* — accession, trait, population, sample
  size, URL — which no data file states about itself, and which the `gwas-catalog-lookup` and
  `qtl-data-finder` skills fetched from the source.

```bash
M=qtl-data-agent/skills/sumstats-manifest/scripts/manifest.py
STORE=sumstats_metadata.jsonl

# upstream, once per dataset — writes the store
python3 …/find_gwas.py "basophil count"      --save-metadata $STORE
python3 …/find_qtl.py  resolve QTD000574     --save-metadata $STORE

python3 $M inspect data/GTEx_v10/Whole_Blood.v10.eqtl.tsv.gz     # look first, always

# stage 4: fill the review table's layout columns from the files on disk
python3 $M fill-table qtlliteraturereview-2026-09-01.dedup.tsv --rows 5

python3 $M add-gwas data/GCST90002296.tsv.gz \
    --accession GCST90002296 --metadata $STORE
python3 $M add-qtl  data/QTD000574.all.tsv.gz \
    --dataset PISA --qtl-type eQTL --biocontext pancreatic_islet --metadata $STORE
python3 $M validate qtl --manifest qtl_manifest.tsv               # after any edit
```

Standard library only. Handles `.gz` and plain text, sniffs the delimiter, and accepts a glob for
sharded datasets.

## `fill-table` — what the downloaded files actually contain

```bash
python3 $M fill-table qtlliteraturereview-2026-09-01.dedup.tsv
```

For every row `download-qtl` marked `downloaded`, this reads the header and first few data rows of
`local_path`, sniffs the delimiter, maps the columns, and writes back:

```
delimiter  n_columns  chrom_col  position_col  ref_col  alt_col  beta_col  se_col
pval_col  rsid_col  maf_col  phenotype_id_col  layout_status  missing_columns
```

`layout_status` is the answer the pipeline needs:

| Value | Meaning | What to do |
|---|---|---|
| `complete` | chrom, position, ref, alt, beta and pval all mapped | register it with `add-qtl` |
| `missing-columns` | at least one required slot is absent; `missing_columns` names them | find the right file, or record why it is unusable |
| `unreadable` | the path is gone, empty or not a table; the error is in `missing_columns` | re-download, or fix the path |

Rows already filled are left alone unless you pass `--force`, so a resumed run is cheap. Rows that
were never downloaded are skipped, not guessed at.

`missing-columns` is a real finding, not a formatting problem to work around. A file with no `beta`
column cannot be used for colocalisation whatever the manifest says about it, and `--force` on
`add-qtl` only moves the failure to load time.

## Where the metadata comes from

`--metadata` reads one JSONL record per dataset, upserted by the two lookup skills and keyed on
`accession` (GWAS) or `dataset|qtl_type|biocontext` (QTL). Passing a partial identifier works when
it matches exactly one record; otherwise the error lists the candidates.

**Any flag you pass overrides the store.** That is the escape hatch for the fields the upstream
skills cannot get right on their own:

- **`--type cc`** for a binary GWAS trait. The GWAS Catalog API does not distinguish quantitative
  from case/control, so every record says `quant`.
- **`--population`** when the store left it blank. Only 27 of 42 eQTL Catalogue r7 studies have
  ancestry data; the rest are deliberately empty rather than wrongly `ALL`.
- **`--trait`** when the auto-underscored reported trait is not the label you want.

Without `--metadata`, every field must be passed as a flag — fine for a one-off, but then the
sample size in the manifest is whatever was typed, with no record of where it came from. Prefer the
store.

A missing field is an error, not a blank cell: `add-*` refuses and names what is missing.
`level_2_context` is the sole exception, because blank is a real value there.

## Always `inspect` before `add`

`inspect` prints the proposed mapping beside a real value from row 1, so a wrong guess is visible
rather than silently written:

```
  chrom_col          chr                              10
  ref_col            ref                              A
  alt_col            alt                              C
  beta_col           slope                            -0.16363569
  phenotype_id_col   phenotype_id                     ENSG00000261456.6
note      : chr values are unprefixed ('10'), not 'chr10'
```

Unmapped header columns are listed, and missing required slots (`chrom`, `position`, `ref`, `alt`,
`beta`, `pval`) are flagged. `add-gwas`/`add-qtl` refuse to write when a required slot is missing —
`--force` overrides, but a row that fails here will fail at load time too.

## The two conventions that are easy to get backwards

**`ref` is the non-effect allele, `alt` is the effect allele — beta is with respect to `alt`.**
In GWAS Catalog files that means `ref_col=other_allele` and `alt_col=effect_allele`, which reads
backwards next to a VCF where REF/ALT are genomic. Getting this wrong silently flips the sign of
every effect. The synonym table already encodes it; do not "fix" it.

**`gene_id_mode` says how to get a gene out of `phenotype_id`**, and is inferred from the value's
own shape:

| Value in the file | Mode | Typical |
|---|---|---|
| `ENSG00000261456.6` | `self` | eQTL |
| `chr6:32518666:32519370:clu_46120_-:ENSG00000198502.6` | `phenotype_last_segment` | sQTL (leafcutter) |
| `chr1:1000-2000`, `cMono_CD14_peak_12` | *(blank)* | caQTL — no gene |

Override with `--gene-id-mode` when a file breaks the pattern. A blank is a real value here, not a
missing one.

## Schema

`gwas_manifest.tsv` — 19 columns:

```
accession  trait  datasource  population  type  sample_size  file_path  delimiter
chrom_col  position_col  ref_col  alt_col  beta_col  se_col  pval_col  rsid_col
maf_col  variant_id_col  url
```

`qtl_manifest.tsv` — 22 columns:

```
dataset  qtl_type  biocontext  level_1_context  level_2_context  population  sample_size
file_path  delimiter  chrom_col  position_col  ref_col  alt_col  beta_col  se_col
pval_col  rsid_col  maf_col  variant_id_col  phenotype_id_col  gene_id_mode  url
```

Conventions the writer follows and you must preserve when hand-editing:

- `delimiter` holds the **two characters** `\t`, not a tab. A literal tab there breaks the file.
- `trait` is underscored: `Mean_corpuscular_hemoglobin`.
- `type` is `quant` or `cc` (case/control).
- `level_1_context` is the broad tissue and defaults to `biocontext`; `level_2_context` is the cell
  type and stays **blank for bulk tissue** (GTEx `Whole_Blood` has none).
- Empty cells are empty — never `NA`, `None`, or `-`.

Rows are keyed on `accession` (GWAS) and `dataset + qtl_type + biocontext` (QTL). Re-running `add`
with the same key **updates in place**, so correcting a sample size is a re-run, not a hand edit.
One study contributing eQTL and sQTL is two rows, distinguished by `qtl_type`.

## Sharded datasets

Record the glob, not one shard:

```
/data/tenk10k_caqtl/CD14_Mono/TenK10K.cis_qtl_pairs.chr*.tsv.gz
```

`inspect` resolves the pattern, reads the first matching shard for the header, and keeps the
pattern in the manifest — every shard shares a header, so one read is enough. Quote the glob so
the shell does not expand it.

## `validate`

Re-reads every file and checks that each recorded column still exists in its header, the delimiter
still matches, the path still resolves, and `sample_size` is numeric. Run it after hand-editing a
manifest, after moving data, and before any bulk load. It exits non-zero on the first problem, so
it works in a pipeline.

It cannot check what is not in the header: whether `sample_size` is *correct*, whether the
population label is right, or whether `beta` is really on the `alt` allele. Those come from the
paper or the portal — see the `gwas-catalog-lookup` and `qtl-data-finder` skills, which produce
exactly the accession, sample size, and URL this manifest wants.

## Paths

Write absolute paths in `file_path`. Manifests get read from different working directories, and a
relative path that resolved when the row was written is the most common way `validate` starts
failing. Keep the data itself under `data/` — it is gitignored, and manifests must never be
committed with real paths to someone's home directory.
