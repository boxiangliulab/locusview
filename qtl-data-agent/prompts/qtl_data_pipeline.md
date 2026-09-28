# Objective

Build the broadest practical, evidence-backed inventory of published human QTL datasets, and turn
it into summary-statistics files that locusview can load. The deliverable is not a paper list: it
is one review table in which every row ends with a decision, every downloadable dataset has a file
on disk whose column layout has been read, and every dataset that needs a person carries the
contact and the action required.

# The table

Everything flows through one TSV, named `qtlliteraturereview-<search date>.tsv`. Each stage
appends its own block of columns and does not rewrite the earlier ones — except that the verifier
corrects values it checked against the paper, always explaining the correction in `verifier_note`.

# Required workflow

Read a skill's `SKILL.md` before using it. Run the stages in order.

1. **qtl-data-finder — search.** Search Google Search, Google Scholar, Europe PMC and PMC; use `review` across the keyword families:
   molecular QTL type, single-cell/cell-type QTL, context and condition QTL, newly released
   datasets, and large-cohort studies. Search for recall, not precision, preserve every URL/DOI seed (even when data are not found), and record the scope
   searched. Then read every paper that may carry a dataset — Methods, Data Availability,
   supplements, the repository or portal it names — and write what it says back with `update`:
   dataset name, QTL type, context, population, donor sample size, corresponding-author address,
   the summary-statistics download URL, the access route and whether the URL downloads directly.
   `download_url` holds association-level statistics only: never a DOI or article page, never
   FASTQ/genotype/expression/peak data, never a portal landing page recorded as `direct`.

2. **qtl-record-verifier — check.** Run `dedupe` so one dataset is one row, keeping the earliest
   published paper in each group and marking the rest as duplicates that name what they duplicate.
   Run `check-urls` so every `download_url` is confirmed to resolve. Then re-check each row against
   the paper — QTL type, context, donor sample size (never cell count), population, access route —
   correct what is wrong, and set `verify_status`: `verified` for directly downloadable statistics,
   `public-access` for anonymous repositories/buckets/portals that require file selection but no
   permission, `needs-request` for data a person must obtain, `rejected` with a reason for papers that only
   reuse QTL data for MR/TWAS/SMR/colocalisation or that are reviews, methods-only or non-human.
   Every `needs-request` row must carry an `access_action` and a contact or application URL.
   If documentation claims public access but a real object read returns 401/403 or a storage-policy
   denial, use `access_route=blocked` and `access_action=repair-access`; do not trust the landing page.
   Finish with `validate --ready-out`, which fails while any row is still unresolved.

3. **download-qtl — fetch.** Download only rows that are `verified`, `direct`, `direct_download=yes`
   and `url_status=ok`. Everything else is skipped with its reason recorded. Files land under
   `data/qtl/` as `<record_id>-<filename>`. Failures stay retryable; never work around the gate by
   fetching a URL the verifier did not clear.

4. **sumstats-manifest — read the files.** Run `fill-table` to read the head of every downloaded
   file and record its delimiter and column mapping in the table. A row is usable only when chrom,
   position, ref, alt, beta and p-value all map, and beta must be with respect to the alt/effect
   allele. Then register usable files with `add-qtl` using evidence-backed provenance and run
   `validate qtl`. Never use `--force` to conceal a missing column.

# Completion rules

- Every candidate ends in a decision: `verified`, `public-access`, `needs-request`, `rejected` or `duplicate`.
  A row left `unresolved` means the run is unfinished.
- A dataset is complete only when it has been downloaded, its layout read, and its manifest row
  registered and validated.
- Non-public datasets stay in the table with their access route, contact and required human action.
  Drafting a request email is allowed; sending it is not — report it in the human-action queue and
  remind the operator explicitly.
- Report totals by `verify_status`, QTL type, access route and download status, and list every
  failed, unreadable and unresolved row.
