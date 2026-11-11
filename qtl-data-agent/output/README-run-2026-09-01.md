# QTL literature run — 2026-09-01

Produced by `qtl-data-finder` (stage 1) and `qtl-record-verifier` (stage 2). Files from this run
all start with `qtl` and a hyphen; the older `human_*` tables are a separate, earlier sweep.

## What was searched

Europe PMC, 30 queries across the five keyword families (`molecular-type`, `single-cell`,
`context`, `new-release`, `large-sample`), each paginated with `cursorMark` past the
1,000-results-per-request cap, scoped to human studies.

**13,217 unique papers.** Two findings from this run were folded back into the skill:

- the old default scope `human OR Homo sapiens` returned 964 papers for the eQTL family where the
  broader human phrasing returns 4,000+ — most human QTL papers write *donors*, *cohort* or
  *patients*, never either phrase;
- without `cursorMark`, every additional tissue-scoped sweep returned papers already held, because
  they all rank inside the first page.

## What was read

Every one of the 13,217 rows was read: **10,314 at full text** (Europe PMC `fullTextXML`, Data
Availability section and the URLs in it) and 2,903 at abstract level, where no open-access full
text exists. Extraction proposes `qtl_type`, `qtl_context`, `population`, `sample_size`,
`download_url`, `access_route` and `direct_download`, and records the sentence it came from in
`extraction_note`.

## What was checked

- `dedupe` grouped 13,217 rows into **11,510 datasets**, keeping the earliest publication in each
  group and marking 1,707 rows as duplicates of it.
- `check-urls` confirmed the direct and supplement links with HEAD, falling back to a ranged GET:
  **260 resolve, 67 are dead.**
- URLs that resolve but are not the study's own QTL statistics were demoted with a reason — GENCODE
  and Ensembl references, LD panels, BLAST databases, GTEx expression matrices, FinnGen/Pan-UKB
  GWAS releases, and journal article pages recorded as if they were data portals.

## Which dataset each paper used

Every one of the 13,217 papers was re-read through the full source ladder: **9,621 at full text**
(Europe PMC), 918 rescued by the fallbacks (publisher pages 504, OpenAlex 384, Crossref 24,
Semantic Scholar 10), 2,455 at abstract level, and 219 that yielded nothing anywhere.

Then `name-datasets` matched the Methods text against the registry and `datasets` rolled the table
up: **60 distinct QTL datasets — 53 primary studies and 7 catalogues — named across 1,851 papers.**
Deduplication merged 3,139 rows into 10,078 groups.

## Re-screening the human-action queue

The 212 rows parked for a person were read again. In 26 of them the data statement named a public
deposit that the first pass had missed, because the URL it picked was a landing page, a code repo
or — twice — the analysis software's homepage. Two gaps caused it, both now closed:

- **deposits written as DOIs, not links**: `10.5281/zenodo.…`, `10.6084/m9.figshare.…`,
  `10.5061/dryad.…`, `10.17044/scilifelab.…`, plus Synapse `syn…` and PRIDE `PXD…` accessions;
- **software and documentation hosts** (readthedocs, CRAN, Bioconductor, `*.github.io`) scoring as
  download URLs.

Each candidate was confirmed with a HEAD request before the row moved. A public repository record
must take `verify_status=public-access` only after the repository contents, not merely its landing
page, have been checked. The 2026-09-07 audit withdrew earlier automatic promotions because some
resolving Zenodo links were code rather than QTL statistics. The request queue currently has
**214 rows**; 5,541 rows remain unresolved and must not be described as verified.

## Files

| File | Rows | What it is |
|---|---|---|
| `qtl-unique-datasets-2026-09-01.tsv` | 140 | Candidate dataset roll-up; access/status columns must be consulted, and this is not a fully verified conclusion while unresolved rows remain |
| `qtl-datasets-hand-checked-2026-09-01.tsv` | 14 | Resources checked one by one, including release year and the exact access mechanism |
| `qtl-datasets-request-queue-2026-09-01.tsv` | 214 | Rows that need a person: application, author email, gated/interactive export, broken deposit or access-policy repair |
| `qtlreview-verified-2026-09-01.tsv` | 13,217 | Master table: every paper read, named, deduplicated and decided |
| `README-run-2026-09-01.md` | — | This file |

### Unregistered datasets

A dataset the registry has no name for is still a dataset, and dropping those is what kept the
earlier list to famous resources. A row joins the table as `kind=unregistered dataset` when the
pipeline judged it a QTL dataset, it names a QTL type, and its own deposit URL resolves. It is
labelled by first author and year, because the study has no other name. Rows with a public deposit
but no QTL-dataset judgement — tool papers, a pangenome, the cattle and plant studies — are not
included; that filter is the difference between 32 rows and 340.

### Reading the dataset table

- `earliest_paper_year` is the earliest paper **in this corpus** that names the dataset. It is the
  release year only when that paper is the dataset's own — GTEx shows 2012 because a 2012 paper
  cites it, not because GTEx was released then. Verified release years are in the hand-checked file.
- **Two donor counts, and they are not the same number.** `study_donors` is the project's own
  figure, taken from that study's paper abstract with the sentence kept in
  `study_donors_evidence` — GTEx is **838 donors**. `url_dataset_donors` is how many donors
  contributed the one context the URL points at — GTEx muscle is 702, because no single tissue was
  sampled from all 838. `study_donors` is filled for the 5 studies whose abstract states it and
  blank for the rest, which do not.
- **Donor counts belong to a context, not to a study.** GTEx is 245 datasets across 48 tissues in
  eQTL Catalogue r7, with donor counts from 73 to 702; quoting 702 as "GTEx's sample size" is
  wrong. So the table reports `catalogue_datasets` (how many the study has), `catalogue_donor_range`
  (min–max across them), and then `url_dataset_id` / `url_dataset_context` / `url_dataset_donors`
  for the one context the URL actually points at. These come from the catalogue index, not from
  text, and are blank for the 39 datasets the catalogue does not redistribute.
- **The URL points at one context, not the whole study.** GTEx's link here is skeletal muscle gene
  expression. Use `qtl-data-finder search`/`resolve` to get the file for the context you want.
- `dataset_url_status` is a live HEAD result: 32 resolve, 6 are dead, and the dead ones say so in
  `url_evidence`.
- A blank is "no evidence found", never "none exists". 21 datasets have no URL here because nothing
  in the corpus or the catalogue tied one to them.

## How a URL gets attributed to a dataset

Only two ways, because a paper that merely cites GTEx still has a data statement of its own, and
taking its URL as GTEx's is how a first attempt claimed CommonMind was distributed as a senescence
gene list and deCODE by r-project.org:

1. the URL carries the dataset's own name; or
2. it is a **deposit** — `direct` or `supplement` — from the earliest paper naming that dataset.

Code repositories are excluded either way: a repo named after a dataset is its analysis code.
37 of the 60 datasets have a URL that clears this bar; the rest are listed without one.

## What these numbers do not mean

**The 52 datasets are what the corpus *names*, not everything that exists.** A dataset only appears
if a paper in this sweep mentions it by a name the registry knows. Datasets released under a name
the registry lacks are invisible — extending the registry is the direct way to improve this number,
and three alias bugs found while building it (case-insensitive acronyms, a bare `INTERVAL` matching
the English word, `DICE` matching a migraine consortium) are the kind of error to expect from a new
entry.


**No row here is human-verified.** `qtl_type`, `qtl_context`, `population` and especially
`sample_size` are machine-extracted from the text, and `sample_size` is the least reliable of them
— the six `verified` rows carry that caveat in `verifier_note`. Before any of this is loaded into
locusview, a person has to confirm, per row, that the paper released the dataset, that the donor
count is the donor count, and that the URL is the statistics file rather than something beside it.

Rejections are rule-based and auditable — `verifier_note` names the rule that fired (non-human
organism, classical linkage-mapping QTL, review, or downstream MR/TWAS/colocalisation reuse) — but
they are rules, not readings, and a wrongly rejected row will say why it was rejected.

The 7,011 unresolved rows are unresolved on purpose: `validate` fails while any remain, which is
the correct state for a run whose reading was automated.
