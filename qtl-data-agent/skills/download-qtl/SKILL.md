---
name: download-qtl
description: Download the QTL summary-statistics files that qtl-record-verifier cleared, straight from the verified download URLs in a qtlliteraturereview table, and record where each file landed, how large it is and why any row was skipped or failed. Use after verification and before sumstats-manifest; it refuses portal, controlled-access, request-only and unverified rows rather than guessing a URL.
---

# download-qtl — stage 3 of 4

The only stage that writes files to disk. It fetches nothing that the verifier has not cleared.

```bash
D=qtl-data-agent/skills/download-qtl/scripts/download_qtl.py
T=qtlliteraturereview-2026-09-01.dedup.tsv

python3 $D download $T --out-dir data/qtl --dry-run     # what would be fetched
python3 $D download $T --out-dir data/qtl --limit 10    # fetch the first 10
python3 $D status   $T                                  # downloaded / pending / failed / waiting
python3 $D download $T --out-dir data/qtl --retry-failed
```

Standard library only. The table is updated in place after each run.

## The gate

A row is fetched only when **all four** hold:

```
verify_status  = verified
direct_download = yes
access_route   = direct
url_status     = ok
```

Anything else is marked `download_status=skipped` with the reason in `download_error`. A
`public-access` row needs its public bucket/repository opened and the relevant files selected; a
`needs-request` row needs a controlled-access application or an email to the authors. The rule
is not a formality — an unverified URL is as likely to be a landing page or a genotype archive as
a statistics file, and both download without complaint.

A `blocked/repair-access` row is also never downloaded: its documentation may say public, but a
real object read failed. Report the exact HTTP/policy error so a maintainer can restore access or
provide a mirror.

There is no flag to fetch an unverified row. If a row should be downloadable, fix it upstream:
record the real file URL with `qtl-data-finder update`, re-run `qtl-record-verifier check-urls`,
then come back.

## Where files land

`data/qtl/<record_id>-<filename from the URL>`, e.g. `data/qtl/42-OneK1K_CD4_naive.all.tsv.gz`.

The record id prefix keeps two datasets that share a server-side filename apart, and makes the file
traceable back to its row. `data/` is gitignored — never commit downloaded statistics.

Downloads stream to a `.part` file and are renamed on success, so an interrupted run never leaves a
truncated file that looks complete.

## Resuming

Re-running is cheap and safe:

- rows already `downloaded` whose file still exists are skipped;
- rows that `failed` are skipped until `--retry-failed`, so one dead host does not stall the run;
- `--limit N` fetches at most N files, which is how a large table is worked through in batches;
- `--force` re-fetches a row whose file is already on disk.

Every row keeps `download_status`, `local_path`, `file_bytes`, `download_date` and
`download_error`, so a resumed run knows exactly what is left.

## `status`

Prints the counts and then the two lists that need a human:

- **failed, retryable** — with the error each one stopped on;
- **waiting on a person** — every `needs-request` row, with its `access_action` and contact.

Report both at the end of a run. A dataset waiting on an email is not a finished dataset, and it
is the item most easily lost between runs.

## Column reference — the block this skill owns

```
download_status  local_path  file_bytes  download_date  download_error
```

`download_status` is one of `downloaded`, `failed`, `skipped`, or blank for not-yet-attempted.
Nothing else in the table is rewritten.

Next: `sumstats-manifest fill-table` reads the first lines of each downloaded file and records what
is actually in it.
