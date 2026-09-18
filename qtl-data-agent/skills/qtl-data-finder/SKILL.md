---
name: qtl-data-finder
description: Search the published literature for human QTL datasets through the Europe PMC API, using keyword families for QTL type, single-cell and cell-type QTL, context/condition QTL, newly released datasets and large-cohort studies; then read each paper that carries a dataset, extract its summary-statistics download URL, judge whether that URL is directly downloadable, and record everything in one dated qtlliteraturereview TSV table. Use to start a QTL data hunt, widen an existing sweep, or record what reading a paper established.
---

# QTL data finder — stage 1 of 4

Turn the literature into one table. Every later stage reads and appends to that table:

```
qtl-data-finder → qtl-record-verifier → download-qtl → sumstats-manifest
```

The table is named `qtlliteraturereview-<search date>.tsv`, e.g.
`qtlliteraturereview-2026-09-01.tsv`. One row is one candidate dataset.

```bash
F=qtl-data-agent/skills/qtl-data-finder/scripts/find_qtl.py

# 1. sweep Europe PMC across every keyword family → qtlliteraturereview-<today>.tsv
python3 $F review "human"

# narrower scope, or one family at a time
python3 $F review "human AND brain" --families single-cell context --top-per-query 200
python3 $F review "human" --families large-sample --append      # add to today's table

# 2. read each paper, then record what it actually says
python3 $F update qtlliteraturereview-2026-09-01.tsv 42 \
    --set dataset_name=OneK1K --set qtl_type=eQTL \
    --set qtl_context=PBMC_CD4_naive --set population=EUR --set sample_size=982 \
    --set download_url=https://…/OneK1K_CD4_naive.all.tsv.gz \
    --set access_route=direct --set direct_download=yes \
    --set "extraction_note=Data availability, para 2: GCS bucket, no registration"

# helpers
python3 $F papers '"pancreatic islet" eQTL' --top 50 --append qtlliteraturereview-2026-09-01.tsv
python3 $F search "pancreatic islet" --release r7          # eQTL Catalogue index
python3 $F resolve QTD000574 --save-metadata sumstats_metadata.jsonl
python3 $F draft --citation "Smith et al. (2024) Nat Genet" --title "…" --out request.txt
```

Standard library only, no `uv sync`. The eQTL Catalogue index is cached under
`~/.cache/locusview-qtl-finder/`.

## Step 1 — sweep for candidates

`review` runs every query in the chosen families against Europe PMC and merges the hits,
deduplicated on PMID/DOI. Recall matters more than precision here: a paper wrongly kept costs one
verification, a paper never found is invisible for good.

| Family | What it reaches |
|---|---|
| `molecular-type` | eQTL (cis and trans), sQTL, pQTL, caQTL, meQTL, hQTL, metabolite/lipid/ribo/miRNA QTL |
| `single-cell` | scQTL, sc-eQTL, cell-type-specific, pseudobulk, cell-state, single-nucleus, OneK1K/DICE/sc-eQTLGen |
| `context` | context-dependent, response/dynamic/interaction QTL, stimulation, disease state, development, tissue and cell type |
| `new-release` | papers announcing a resource, atlas, catalogue or data release |
| `large-sample` | biobank, consortium and meta-analysis studies; the named large resources |
| `all` | every family (default) |

`--top-per-query` pages past Europe PMC's 1,000-result-per-request cap with `cursorMark`, so a
query with 20,000 hits is not silently truncated at the first thousand. Recall stalls without it:
scoping the same sweep to a tissue returns papers you already have, because they all rank inside
that first page. Raise it when a family looks under-sampled, and expect the run to take longer.

Record the scope you searched — organism, tissue, condition, ancestry, date range — in the run
report. `search_terms` on each row already records which families found it, and `search_date`
records when.

## Step 2 — read the paper, through every source it takes

A `review` row is a literature hit. It becomes a dataset row only after the paper is read: the
Methods, the Data Availability statement, the supplement, and any repository or portal it names.

```bash
python3 $F read qtlliteraturereview-2026-09-01.tsv          # read every unread row
python3 $F read qtlliteraturereview-2026-09-01.tsv --limit 500 --workers 16
python3 $F read qtlliteraturereview-2026-09-01.tsv --reread  # re-read rows already read
```

**Europe PMC is the first source, never the only one.** It carries full text only for the PMC
open-access subset and has no abstract at all for a large share of records. A reader that stops
there marks most of the literature "no data route found" — measured on this corpus, Europe PMC
alone reached about one paper in eight; the ladder below reaches the rest. `read` walks it in cost
order and records which rung answered in `evidence_source`:

| `evidence_source` | Source | Why it is on the ladder |
|---|---|---|
| `europepmc-fulltext` | Europe PMC `fullTextXML` | The Data Availability section itself, when the paper is in PMC OA |
| `openalex-abstract` | OpenAlex | Abstracts Europe PMC lacks, plus OA and landing-page locations |
| `crossref-abstract` | Crossref | Publisher-deposited abstracts, including closed-access journals |
| `semanticscholar` | Semantic Scholar | Another abstract index, and an open PDF link when one exists |
| `publisher-page` | Unpaywall → the article page | Reaches papers no API indexes; publishers often serve Data Availability in the landing HTML |
| `abstract-only` | whichever abstract was found | No data statement anywhere — the row states what little is known |
| `not-found` | — | Nothing from any source; search for it by title before writing it off |

The last two rungs — Unpaywall and page fetching — run only for papers that name a QTL or say
something about data availability. Running them on every hit costs hours and changes nothing for a
paper that mentions neither.

When even `read` comes back `not-found` or `abstract-only` for a paper that clearly matters, search
for it by title on the open web and read whatever you find. That step is a person's or an agent's,
not the script's, and what it establishes goes in through `update` like any other reading.

Write the result back with `update`.

`update` sets these fields and refuses anything else:

| Field | What it must hold |
|---|---|
| `dataset_name` | the study/cohort/project name a later stage can group on (GTEx_v10, OneK1K, eQTLGen) |
| `qtl_type` | eQTL, sQTL, pQTL, caQTL, meQTL, hQTL, metabolite-QTL — semicolon-separated if the paper released several |
| `qtl_context` | the specific tissue, cell type, cell state or condition the dataset is for |
| `population` | ancestry of the donors, blank if the paper does not say |
| `sample_size` | **donor count**, as a plain integer — never the cell count |
| `contact_email` | corresponding author, prefilled from the affiliation string when Europe PMC has one |
| `download_url` | the URL of the association-level statistics themselves |
| `access_route` | direct, portal, supplement, controlled, request, blocked, unavailable |
| `direct_download` | yes, no, unknown |
| `extraction_note` | where in the paper this came from — the sentence or section, not "verified" |

One paper releasing eQTL and sQTL for three tissues is six datasets. Run `update` on the first
row, then add rows for the rest by re-running with the same `dataset_name` and different
`qtl_context`; the verifier keeps them apart on exactly those fields.

## Naming the dataset each paper used

```bash
python3 $F name-datasets qtlliteraturereview-2026-09-01.tsv
```

Which QTL dataset a paper used is almost never in a structured field — it is a name in the Methods.
`name-datasets` matches those names against a registry of known QTL resources (GTEx, eQTLGen,
DICE, OneK1K, UKB-PPP, deCODE, GoDMC, BLUEPRINT, PsychENCODE, iPSCORE, …) and writes them into
`dataset_name`.

This is not cosmetic. `qtl-record-verifier dedupe` keys on `dataset_name + qtl_type + qtl_context`;
with the column empty it can only merge rows that share a URL, and a corpus of thousands of papers
collapses to almost nothing. Filling it is what turns the table into a list of datasets.

Two rules the registry has already been burned by:

- **Match acronyms case-sensitively.** Under `re.I`, `\bMESA\b` also matches "mesa", `\bDICE\b`
  matches "dice", and a bare `INTERVAL` matches the English word — one of those filed a 1994 paper
  on interval mapping under the INTERVAL pQTL cohort. Acronym aliases are wrapped in `(?-i:...)`.
- **Give a generic acronym a disambiguating word.** `DICE` alone also names the Dutch-Icelandic
  migraine consortium, so its alias requires `DICE database|project|data|eQTL` or the spelled-out
  name. Check a new acronym against the corpus before trusting its count.

Catalogues that redistribute other people's statistics — eQTL Catalogue, QTLbase, PhenoScanner,
IEU OpenGWAS, scQTLbase — are in the registry but marked as catalogues, because counting them
beside primary studies overstates both.

## What `download_url` may point at

**Only association-level QTL statistics**: variant, gene/phenotype, beta, p-value. That is the file
locusview loads.

Not summary statistics, and never acceptable in `download_url`:

- a DOI, journal page or PMC article link — that is `publication_url`;
- raw data: FASTQ, BAM, CRAM, genotype VCF, dbGaP/EGA/SRA accessions;
- expression, count or peak matrices, or processed single-cell objects;
- a portal *landing page* — record it, but with `access_route=portal`, not `direct`.

If the paper points at the eQTL Catalogue, use `search` and `resolve` to get the verified file URL
rather than constructing one; `resolve` also writes the dataset's provenance into the shared
metadata store that `sumstats-manifest` reads later.

## Judging `direct_download`

`direct_download=yes` means: this URL returns the file to an unauthenticated HTTP client, with no
login, no form, no application, no email. Everything else is `no`, and the reason belongs in
`access_route`:

| `access_route` | The situation | `direct_download` |
|---|---|---|
| `direct` | FTP/HTTPS/cloud object whose bytes were fetched anonymously | `yes` |
| `portal` | results are queryable or exportable, but no bulk file is offered | `no` |
| `supplement` | statistics live in a supplementary or source-data file | `no` |
| `controlled` | dbGaP, EGA or an institutional application stands in the way | `no` |
| `request` | the paper says the data are available from the authors | `no` |
| `blocked` | documentation claims public access, but the actual object/listing returns 401/403 or an access policy error | `no` |
| `unavailable` | no route found in the paper, the repository, or the portal | `no` |

Use `unknown` only while the reading is unfinished — the verifier rejects it.

`draft` writes an email asking for data that cannot be downloaded. It writes a file for a person to
review and send. **It never sends anything, and neither do you.**

## Column reference — the block this skill owns

```
record_id  publication_title  publication_url  doi  pmid  first_author  authors  year
journal  contact_email  qtl_type  qtl_context  population  sample_size  dataset_name
download_url  access_route  direct_download  extraction_note  evidence_source
search_terms  search_date
```

`qtl-record-verifier`, `download-qtl` and `sumstats-manifest` append their own blocks to the right
of these and do not rewrite them — except where the verifier corrects a value it checked against
the paper, which it then explains in `verifier_note`.

## Traps this already handles — do not "simplify" them away

- **`hasData` and accession numbers do not mean QTL statistics.** A GEO accession beside a QTL
  paper is usually the expression data the mapping was run on. Leave `download_url` blank rather
  than filling it with the first accession you see.
- **The abstract cannot tell you the access route.** "Summary statistics are publicly available"
  appears in papers whose data are behind dbGaP. The Data Availability statement, followed by the
  link itself, is the only evidence that counts.
- **The families overlap on purpose.** A large single-cell resource paper is found by three of
  them; the sweep merges on PMID/DOI, so the cost is one API call, and the gain is that no single
  phrasing decides whether a dataset is ever seen.
- **A URL that downloads is not therefore the right file.** Data Availability sections are full of
  GENCODE annotation, Ensembl builds, LD reference panels, BLAST databases, expression matrices and
  FinnGen or UK Biobank *trait* GWAS releases. All of them resolve; none of them is the study's own
  molecular QTL statistics. `read` demotes them by name and says which kind it found, and
  `qtl-record-verifier` checks what the server actually returns.
- **A README saying “public” is not proof of access.** For a bucket, test an object or recursive
  listing using the documented anonymous client. A landing page returning 200 while the bucket
  returns 403 is `access_route=blocked`, never `direct` or `public-access`.
- **`sample_size` is donors, not cells.** A single-cell paper reporting 1.2 million cells from 982
  donors has `sample_size=982`. This is the most common wrong number in the table.
