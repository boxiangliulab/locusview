#!/usr/bin/env python3
"""Download the QTL summary statistics that the verifier cleared, and record the result.

Subcommands:
  download  fetch every download-ready row into a directory, resumable
  status    report what has been downloaded, what is pending, and what failed

Stage 3 of the pipeline. A row is fetched only when qtl-record-verifier left it as
verify_status=verified, direct_download=yes, access_route=direct and url_status=ok.
Anything else — portal exports, controlled access, author requests — is skipped with
a reason, never guessed at. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

UA = "locusview-download-qtl/1.0 (https://github.com/boxiangliulab/locusview)"
CHUNK = 1024 * 1024

# Columns this skill owns; every other column belongs to an earlier stage.
DOWNLOAD_COLUMNS = ("download_status", "local_path", "file_bytes", "download_date",
                    "download_error")

REQUIRED_SOURCE_COLUMNS = (
    "record_id", "download_url", "access_route", "direct_download", "verify_status",
    "url_status",
)

DOWNLOAD_STATUS = {"downloaded", "failed", "skipped", ""}


def delimiter(path: Path) -> str:
    return "," if path.suffix.casefold() == ".csv" else "\t"


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter(path))
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    if not fields:
        raise ValueError(f"table has no header: {path}")
    missing = [c for c in REQUIRED_SOURCE_COLUMNS if c not in fields]
    if missing:
        raise ValueError(
            f"{path} has not been through qtl-record-verifier; missing: {', '.join(missing)}"
        )
    return fields, rows


def write_table(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter(path))
        writer.writeheader()
        writer.writerows(rows)


def with_download_columns(fields: list[str], rows: list[dict[str, str]]) -> list[str]:
    out = fields + [c for c in DOWNLOAD_COLUMNS if c not in fields]
    for row in rows:
        for column in DOWNLOAD_COLUMNS:
            row.setdefault(column, "")
    return out


def blocked_reason(row: dict[str, str]) -> str:
    """Why this row must not be fetched — empty string means it is clear to download."""
    if row.get("verify_status", "").strip() != "verified":
        return f"verify_status={row.get('verify_status', '') or 'unset'!r}, not verified"
    if row.get("direct_download", "").strip() != "yes":
        return "direct_download is not yes"
    if row.get("access_route", "").strip() != "direct":
        return f"access_route={row.get('access_route', '')!r} needs a person, not a download"
    if row.get("url_status", "").strip() != "ok":
        return "download_url has not been confirmed to resolve; run check-urls"
    url = row.get("download_url", "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "download_url is not an HTTP(S) URL"
    return ""


def destination_for(row: dict[str, str], out_dir: Path) -> Path:
    """A stable, record-scoped filename; the server's name is kept where it has one."""
    url = row.get("download_url", "").strip()
    name = Path(urllib.parse.urlparse(url).path).name
    safe = "".join(c for c in name if c.isalnum() or c in ".-_")
    record = row.get("record_id", "0")
    return out_dir / f"{record}-{safe or 'qtl-summary-stats.tsv'}"


def fetch(url: str, destination: Path, *, timeout: int) -> int:
    """Stream to a .part file so an interrupted run never leaves a half file in place."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as out:
        while chunk := response.read(CHUNK):
            out.write(chunk)
    partial.replace(destination)
    return destination.stat().st_size


def download_all(
    table: Path,
    out_dir: Path,
    *,
    limit: int,
    timeout: int,
    retry_failed: bool,
    force: bool,
    dry_run: bool,
) -> Counter[str]:
    fields, rows = read_table(table)
    fields = with_download_columns(fields, rows)
    counts: Counter[str] = Counter()
    fetched = 0
    today = date.today().isoformat()

    for row in rows:
        reason = blocked_reason(row)
        if reason:
            if row.get("download_status", "") != "downloaded":
                row["download_status"] = "skipped"
                row["download_error"] = reason
            counts["skipped"] += 1
            continue

        status = row.get("download_status", "")
        existing = Path(row["local_path"]) if row.get("local_path") else None
        if status == "downloaded" and existing and existing.is_file() and not force:
            counts["already downloaded"] += 1
            continue
        if status == "failed" and not (retry_failed or force):
            counts["failed (not retried)"] += 1
            continue
        if limit and fetched >= limit:
            counts["pending"] += 1
            continue

        destination = destination_for(row, out_dir)
        if dry_run:
            print(f"would fetch record {row['record_id']}: {row['download_url']} → {destination}")
            counts["would fetch"] += 1
            continue
        try:
            size = fetch(row["download_url"], destination, timeout=timeout)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            row["download_status"] = "failed"
            row["download_error"] = f"{type(exc).__name__}: {exc}"
            row["download_date"] = today
            counts["failed"] += 1
            print(f"record {row['record_id']}: {row['download_error']}", file=sys.stderr)
            continue
        row["download_status"] = "downloaded"
        row["local_path"] = str(destination)
        row["file_bytes"] = str(size)
        row["download_date"] = today
        row["download_error"] = ""
        fetched += 1
        counts["downloaded"] += 1
        print(f"record {row['record_id']}: {destination} ({size / 1e6:.1f} MB)")

    if not dry_run:
        write_table(table, fields, rows)
    return counts


def status(table: Path) -> int:
    fields, rows = read_table(table)
    with_download_columns(fields, rows)
    counts = Counter(row.get("download_status", "") or "pending" for row in rows)
    print("download_status:", dict(counts))
    ready = [r for r in rows if not blocked_reason(r) and r.get("download_status") != "downloaded"]
    failed = [r for r in rows if r.get("download_status") == "failed"]
    public_manual = [
        r for r in rows
        if r.get("verify_status") == "public-access"
    ]
    waiting = [
        r for r in rows
        if r.get("verify_status") == "needs-request"
    ]
    print(f"ready to download : {len(ready)}")
    print(f"failed, retryable : {len(failed)}")
    print(f"public, open record: {len(public_manual)}")
    print(f"waiting on a person: {len(waiting)}")
    for row in failed[:10]:
        print(f"  record {row['record_id']}: {row.get('download_error', '')}", file=sys.stderr)
    for row in waiting[:10]:
        print(
            f"  record {row['record_id']}: {row.get('access_action', 'action not set')} — "
            f"{row.get('contact_email', 'no contact recorded')}",
            file=sys.stderr,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("download", help="fetch every download-ready row")
    p.add_argument("table", type=Path, help="the validated review table")
    p.add_argument("--out-dir", type=Path, default=Path("data/qtl"))
    p.add_argument("--limit", type=int, default=0, help="fetch at most N files this run")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--retry-failed", action="store_true", help="try rows that failed before")
    p.add_argument("--force", action="store_true", help="re-fetch even if the file exists")
    p.add_argument("--dry-run", action="store_true", help="list what would be fetched")

    p = subparsers.add_parser("status", help="what is downloaded, pending, failed or waiting")
    p.add_argument("table", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "status":
            return status(args.table)
        counts = download_all(
            args.table,
            args.out_dir,
            limit=args.limit,
            timeout=args.timeout,
            retry_failed=args.retry_failed,
            force=args.force,
            dry_run=args.dry_run,
        )
        print(dict(counts))
        if counts["failed"]:
            print(
                "failed rows keep their error and are retried with --retry-failed",
                file=sys.stderr,
            )
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
