---
name: qtl-record-verifier
description: Check a qtlliteraturereview table row by row — group rows describing the same QTL dataset, keep the earliest paper, test actual file bytes instead of trusting landing pages, verify sample size/context/QTL type, and distinguish direct, public, blocked, controlled and request-only access. Use after qtl-data-finder and before download-qtl.
---

# QTL record verifier — stage 2 of 4

Stage 1 was optimised for recall, so the table it wrote contains the same dataset more than once,
URLs that have rotted, and numbers copied from abstracts. This stage turns it into one row per
dataset, each with a decision.

```bash
V=qtl-data-agent/skills/qtl-record-verifier/scripts/verify_qtl.py
T=qtlliteraturereview-2026-09-01.tsv

# 1. one dataset per row: keep the earliest paper, mark the rest as duplicates
python3 $V dedupe $T --out $T.dedup.tsv --report $T.duplicates.tsv

# 2. confirm bytes can actually be read (ranged GET; HEAD is not sufficient)
python3 $V check-urls $T.dedup.tsv

# 3. after reviewing every row, enforce the rules and write what may be downloaded
python3 $V validate $T.dedup.tsv --ready-out qtl_ready.tsv
```

Standard library only. Nothing here downloads data or sends mail.

## Step 1 — one dataset, the earliest paper

`dedupe` groups rows that share any identity handle and keeps the earliest publication in each
group. The rest are marked `verify_status=duplicate` with `duplicate_of` naming the row that was
kept; nothing is deleted, so the audit trail survives.

Identity handles, strongest first:

1. **the same file** — `download_url` compared on host + path, ignoring scheme and trailing slash;
2. **the same named dataset in the same context** — `dataset_name` + `qtl_type` + `qtl_context`;
3. **the same paper** — DOI or PMID, and only when neither handle above exists;
4. **the same title**, last resort, only when a row has nothing else.

Earliest wins on `year`, then PMID, then `record_id`. This is deliberate: the paper that first
released a dataset is the one to cite and the one whose Methods describe how it was mapped. Later
papers re-releasing it are duplicates, not new datasets.

When the kept row left `download_url`, `access_route`, `direct_download`, `contact_email`,
`sample_size`, `population` or `dataset_name` blank and a duplicate has it, the value is copied
onto the kept row and `verifier_note` records where it came from. Values already present are never
overwritten.

**Two datasets from one paper must not merge.** GTEx v10 whole blood eQTL and GTEx v10 whole blood
sQTL differ in `qtl_type`; two tissues differ in `qtl_context`; two releases differ in
`dataset_name`. If rows collapse that should not have, the missing distinction is in those three
fields — fill it in and re-run, rather than editing the groups by hand.

## Step 2 — confirm the URLs, and confirm what they return

`check-urls` sends a one-byte ranged `GET`, with `HEAD` only as fallback for servers that reject
ranged reads as a method. A successful HEAD alone is insufficient: protected object stores can
serve metadata while denying the file. It writes `url_status` (`ok`, `dead`, `not-checked`, `skipped`),
`url_http_code`, `url_content_type` and `url_bytes`. Duplicates and rows with no URL are skipped.

**Resolving is not the same as being the file.** A landing page answers 200 exactly like a
statistics file does, so the response itself is the evidence: an `access_route=direct` row whose
URL serves `text/html`, or returns fewer than 4 KB, is demoted to `portal` with the reason
recorded. This is the check that catches a stage-1 guess made from the URL's name.

`--routes direct supplement` narrows the work to the routes that matter. On a table of thousands of
rows there is no reason to spend an hour confirming portal and controlled-access landing pages —
their resolving proves nothing about the statistics behind them.

`--limit N` checks at most N URLs per run, so a long table can be worked through in batches.
Re-running skips URLs already `ok` unless you pass `--recheck`.

A dead URL is not a rejection, and a public-access claim returning 403 is not verified: find the
file's new home, `update` the row through `qtl-data-finder`, and check again. Only when no route
exists at all does the row become `access_route=unavailable`.

`rescreen` may find another resolving repository URL in the stored Data Availability statement.
That URL is only a candidate for semantic review; it must not be promoted automatically because a
Zenodo, GitHub or supplement link may contain analysis code or raw data rather than QTL statistics.

## Step 3 — re-check the facts, then decide

For every non-duplicate row, verify against the paper itself — not the abstract, and not the
finder's guess:

| Field | What to confirm |
|---|---|
| `evidence_source` | which source the reading came from — a row read from an abstract alone is weaker evidence than one read from the full text, and is worth re-reading before it is promoted |
| `qtl_type` | the molecular phenotype actually mapped, one row per type |
| `qtl_context` | the tissue, cell type, cell state or condition the file is for |
| `sample_size` | **donor count**, from the Methods; never the cell count |
| `population` | ancestry of the donors as the paper states it |
| `access_route` | what the link really is, after opening it |
| `download_url` | association-level statistics, not raw data, not a landing page |

Correct the value in place and say what you corrected in `verifier_note`. Then set
`verify_status`:

| `verify_status` | Meaning | Requires |
|---|---|---|
| `verified` | directly downloadable summary statistics | `access_route=direct`, `direct_download=yes`, `url_status=ok`, `access_action=none` |
| `public-access` | public repository, bucket or portal; no application/email, but select files or use its client | `access_route=portal` or `supplement`, `direct_download=no`, `url_status=ok`, `access_action=open-record` |
| `needs-request` | a real dataset a person must obtain | a non-direct `access_route`, an `access_action`, and a contact address or application URL |
| `rejected` | not a QTL dataset for locusview | a reason in `verifier_note` |
| `duplicate` | same dataset as an earlier paper | `duplicate_of` |
| `unresolved` | not yet reviewed | nothing — `validate` fails on it |

Reject the papers that only *use* QTL data: Mendelian randomisation, TWAS, SMR, colocalisation and
gene-prioritisation studies release no QTL statistics of their own. So do reviews, methods-only
papers, and non-human work. Say which of those it is in `verifier_note`.

## Marking what a person has to do

Every `needs-request` row names the action. Public records that merely require opening a repository
or selecting files are `public-access`, not requests:

| `access_action` | When |
|---|---|
| `email-author` | the paper says the data are available on request |
| `apply-controlled` | dbGaP, EGA or an institutional application |
| `export-portal` | results exist only behind a query interface |
| `repair-access` | documentation says public, but the real bucket/object is blocked; ask the maintainer to restore access or provide a mirror |
| `find-contact` | no working address or application URL found yet |

`open-record` is reserved for `public-access`: an anonymous repository, bucket or portal whose
files are openly obtainable but which is not one stable HTTP file URL. A portal is not controlled
access merely because an automated downloader cannot fetch the whole collection in one request.
To assign `public-access`, verify a repository file listing or read at least one actual statistics
object. A public-looking HTML page alone is insufficient. Use `access_route=blocked`,
`verify_status=needs-request`, and `access_action=repair-access` when documentation promises public
access but object reads return 401/403, VPC Service Controls, or an equivalent policy denial.

Record the corresponding-author address in `contact_email`, or the application/portal URL in
`download_url`, and write what must be requested in `verifier_note`. `validate` rejects a
`needs-request` row that has none of these — an unactionable row is how a dataset disappears
quietly. `qtl-data-finder draft` writes the request email; a person reviews and sends it.

## Rolling the table up into datasets

```bash
python3 $V datasets $T.dedup.tsv --out qtl-unique-datasets.tsv
```

One dataset is named by many papers: the one that released it, and every paper that later used it.
`datasets` groups the table by `dataset_name` and writes one row per dataset with the number of
papers naming it, the earliest of them (the same rule `dedupe` applies within a group), the best
access route any of them recorded, and the contexts seen.

Two columns are deliberately separate. `qtl_types` is what the registry says the dataset *is*;
`types_mentioned_by_citing_papers` is what the papers naming it happened to mention, which is
noisier — a paper citing GTEx while doing pQTL work makes GTEx look like a pQTL resource if the two
are merged.

`kind` marks catalogues apart from primary datasets. A catalogue redistributing forty studies is
not a forty-first study.

## `validate`

Checks every row and exits non-zero on the first problem, listing all of them. It enforces:

- every row has a decision — `unresolved` is a failure, not a state to ship;
- `verified` means all four of direct route, direct download, resolving URL, no human action;
- `public-access` is an anonymously accessible portal/repository and uses `open-record`;
- `needs-request` never claims `direct_download=yes`, and always names a genuine request action;
- `duplicate_of` points at a record that exists in this table;
- `qtl_type`, `qtl_context` and an integer `sample_size` are present on every real dataset;
- `verified_date` is ISO `YYYY-MM-DD`;
- `rejected` rows say why.

`--ready-out` writes the `verified` rows to their own table. That file is what `download-qtl`
fetches; nothing else is downloadable.

## Column reference — the block this skill owns

```
verify_status  duplicate_of  url_status  url_http_code  url_content_type  url_bytes
access_action  verified_date  verifier_note
```

It also corrects, in place, the finder's `qtl_type`, `qtl_context`, `population`, `sample_size`,
`dataset_name`, `download_url`, `access_route` and `direct_download` — always with an explanation
in `verifier_note`.
