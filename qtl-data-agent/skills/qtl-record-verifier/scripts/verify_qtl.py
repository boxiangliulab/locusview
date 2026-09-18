#!/usr/bin/env python3
"""Check a QTL literature review table: one dataset per row, earliest paper, working URL.

Subcommands:
  dedupe      group rows describing the same dataset, keep the earliest publication
  check-urls  confirm every download_url still resolves (HEAD, then a 1-byte ranged GET)
  validate    enforce the review rules and optionally write the download-ready rows

Stage 2 of the pipeline. It reads the table qtl-data-finder wrote, appends its own
columns, and never rewrites the literature columns — except where it corrects a value
it checked against the paper, which it then explains in verifier_note.
Standard library only. Nothing here downloads data or sends mail.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

UA = "locusview-qtl-record-verifier/1.0 (https://github.com/boxiangliulab/locusview)"

# Columns this skill owns. The finder's columns are read, not rewritten.
VERIFY_COLUMNS = (
    "verify_status",
    "duplicate_of",
    "url_status",
    "url_http_code",
    "url_content_type",
    "url_bytes",
    "access_action",
    "verified_date",
    "verifier_note",
)

# Written by qtl-data-finder; a table without these is not a review table.
REQUIRED_SOURCE_COLUMNS = (
    "record_id",
    "publication_title",
    "year",
    "qtl_type",
    "qtl_context",
    "sample_size",
    "download_url",
    "access_route",
    "direct_download",
)

VERIFY_STATUS = {
    "verified", "public-access", "duplicate", "needs-request", "rejected", "unresolved",
}
ACCESS_ROUTES = {
    "direct", "portal", "supplement", "controlled", "request", "blocked", "unavailable",
    "unknown",
}
NON_PUBLIC_ROUTES = {"controlled", "request", "blocked", "unavailable"}
PUBLIC_MANUAL_ROUTES = {"portal", "supplement"}
ACCESS_ACTIONS = {
    "none", "email-author", "apply-controlled", "export-portal", "repair-access", "find-contact",
    # A public repository record — Zenodo, Figshare, Dryad, PRIDE — is open to anyone; the
    # only human step is choosing which file inside it is the summary statistics. Calling
    # that "request the data" hides an openly available dataset in the human-action queue.
    "open-record",
}
URL_STATUS = {"ok", "dead", "not-checked", "skipped"}

# Filled on the kept row from a duplicate only when the kept row left it blank —
# the group is the same dataset, so a later paper may state what the first omitted.
FILLABLE_FROM_DUPLICATE = (
    "download_url", "access_route", "direct_download", "contact_email",
    "sample_size", "population", "dataset_name",
)


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
            f"{path} is not a qtl-data-finder review table; missing: {', '.join(missing)}"
        )
    return fields, rows


def write_table(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter(path))
        writer.writeheader()
        writer.writerows(rows)


def with_verify_columns(fields: list[str], rows: list[dict[str, str]]) -> list[str]:
    """Add this skill's columns once, with defaults, leaving existing values alone."""
    out = fields + [c for c in VERIFY_COLUMNS if c not in fields]
    for row in rows:
        row.setdefault("verify_status", "unresolved")
        row.setdefault("duplicate_of", "")
        row.setdefault("url_status", "not-checked")
        row.setdefault("url_http_code", "")
        row.setdefault("url_content_type", "")
        row.setdefault("url_bytes", "")
        row.setdefault("access_action", "")
        row.setdefault("verified_date", "")
        row.setdefault("verifier_note", "")
    return out


def note(row: dict[str, str], text: str) -> None:
    existing = row.get("verifier_note", "").strip()
    row["verifier_note"] = f"{existing}; {text}" if existing else text


# ── deduplication: one dataset, the earliest paper ───────────────────────────


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _url_key(value: str) -> str:
    """Same file, ignoring scheme and a trailing slash — enough to catch re-listings."""
    parsed = urlparse((value or "").strip())
    if not parsed.netloc:
        return ""
    return f"{parsed.netloc.casefold()}{parsed.path.rstrip('/').casefold()}"


def identity_keys(row: dict[str, str]) -> set[str]:
    """Every handle by which two rows can be the same dataset.

    A shared *file* is the strongest signal, then a named dataset in the same
    context, then the same paper. Title alone is the last resort, because two
    tissues from one paper are two datasets and must not collapse on it.
    """
    keys: set[str] = set()
    url = _url_key(row.get("download_url", ""))
    if url:
        keys.add(f"url:{url}")
    dataset = _norm(row.get("dataset_name", ""))
    if dataset:
        keys.add(
            "dataset:{}|{}|{}".format(
                dataset, _norm(row.get("qtl_type", "")), _norm(row.get("qtl_context", ""))
            )
        )
    if not keys:
        for field, prefix in (("doi", "doi"), ("pmid", "pmid")):
            value = _norm(row.get(field, ""))
            if value:
                keys.add(f"{prefix}:{value}")
        # The title always joins in when no dataset or file identifies the row. A preprint
        # and its journal version have different DOIs and different PMIDs, so keying only on
        # those leaves the same study sitting in the table twice.
        title = _norm(row.get("publication_title", ""))
        if len(title) > 30:
            keys.add(f"title:{title}")
    return keys


def group_rows(rows: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    """Union rows that share any identity key."""
    parent: dict[int, int] = {index: index for index in range(len(rows))}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    by_key: dict[str, int] = {}
    for index, row in enumerate(rows):
        for key in identity_keys(row):
            if key in by_key:
                union(by_key[key], index)
            else:
                by_key[key] = index
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[find(index)].append(row)
    return [grouped[key] for key in sorted(grouped)]


def _publication_order(row: dict[str, str]) -> tuple[int, int, int]:
    """Earliest first: publication year, then PMID, then the order it was found in."""
    year = row.get("year", "").strip()
    pmid = row.get("pmid", "").strip()
    record = row.get("record_id", "").strip()
    return (
        int(year) if year.isdigit() else 9999,
        int(pmid) if pmid.isdigit() else 10**12,
        int(record) if record.isdigit() else 10**12,
    )


def dedupe(source: Path, destination: Path, report: Path | None) -> tuple[int, int]:
    fields, rows = read_table(source)
    fields = with_verify_columns(fields, rows)
    audit: list[dict[str, str]] = []
    kept = 0
    for group in group_rows(rows):
        group.sort(key=_publication_order)
        keeper, duplicates = group[0], group[1:]
        kept += 1
        if keeper["verify_status"] == "duplicate":
            keeper["verify_status"] = "unresolved"
        keeper["duplicate_of"] = ""
        for duplicate in duplicates:
            duplicate["verify_status"] = "duplicate"
            duplicate["duplicate_of"] = keeper.get("record_id", "")
            for field in FILLABLE_FROM_DUPLICATE:
                blank = keeper.get(field, "").strip() in ("", "unknown")
                value = duplicate.get(field, "").strip()
                if blank and value and value != "unknown":
                    keeper[field] = value
                    note(keeper, f"{field} filled from duplicate record {duplicate['record_id']}")
            audit.append(
                {
                    "kept_record_id": keeper.get("record_id", ""),
                    "kept_year": keeper.get("year", ""),
                    "kept_title": keeper.get("publication_title", ""),
                    "duplicate_record_id": duplicate.get("record_id", ""),
                    "duplicate_year": duplicate.get("year", ""),
                    "duplicate_title": duplicate.get("publication_title", ""),
                    "shared_keys": ";".join(
                        sorted(identity_keys(keeper) & identity_keys(duplicate))
                    ),
                }
            )
    write_table(destination, fields, rows)
    if report is not None:
        write_table(report, list(audit[0]) if audit else ["kept_record_id"], audit)
    return len(rows), kept


# ── URL checking ─────────────────────────────────────────────────────────────


def check_url(url: str, *, timeout: int) -> tuple[str, str, str, str]:
    """Probe with a 1-byte GET, using HEAD only as a fallback.

    Returns status, HTTP code, content type and size. The last two are what tell a real
    file apart from a landing page that happens to answer 200: an `access_route=direct`
    row whose URL serves `text/html` is a web page, whatever its name suggested.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "dead", "not-http", "", ""
    # A successful HEAD does not prove bytes can be downloaded: signed repositories and
    # VPC-protected buckets commonly answer metadata requests but reject object reads.
    for method, headers in (
        ("GET", {"Range": "bytes=0-0"}),
        ("HEAD", {}),
    ):
        request = urllib.request.Request(
            url, method=method, headers={"User-Agent": UA, **headers}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if 200 <= response.status < 300:
                    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
                    size = response.headers.get("Content-Range", "").rpartition("/")[2]
                    size = size if size.isdigit() else response.headers.get("Content-Length", "")
                    return "ok", str(response.status), content_type, size
        except urllib.error.HTTPError as exc:
            if method == "HEAD" or exc.code not in (405, 416, 501):
                return "dead", str(exc.code), "", ""
        except (OSError, TimeoutError, ValueError) as exc:
            if method == "HEAD":
                return "dead", type(exc).__name__, "", ""
    return "dead", "no-response", "", ""


# A file this small is an error page or a stub, whatever its Content-Type says.
MIN_FILE_BYTES = 4096
PAGE_TYPES = ("text/html", "application/xhtml+xml")


def check_urls(
    source: Path,
    destination: Path,
    *,
    timeout: int,
    limit: int,
    recheck: bool,
    routes: set[str] | None = None,
    workers: int = 16,
) -> Counter[str]:
    """Confirm the download URLs resolve. `routes` narrows the work to the routes that matter.

    A portal or controlled-access landing page resolving proves nothing about the statistics
    behind it, so on a large table there is no reason to spend an hour checking those first.
    """
    fields, rows = read_table(source)
    fields = with_verify_columns(fields, rows)
    counts: Counter[str] = Counter()
    candidates: list[tuple[dict[str, str], str]] = []
    for row in rows:
        url = row.get("download_url", "").strip()
        if routes is not None and row.get("access_route", "").strip() not in routes:
            counts["out of scope"] += 1
            continue
        if row.get("verify_status") == "duplicate" or not url:
            row["url_status"] = "skipped"
            counts["skipped"] += 1
            continue
        if row.get("url_status") == "ok" and not recheck:
            counts["ok (cached)"] += 1
            continue
        if limit and len(candidates) >= limit:
            counts["not-checked"] += 1
            continue
        candidates.append((row, url))

    # Check each distinct URL once. Literature sweeps cite the same catalogue thousands
    # of times, so serially probing each row is both slow and unnecessarily hard on hosts.
    distinct = list(dict.fromkeys(url for _row, url in candidates))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = dict(zip(distinct, pool.map(lambda url: check_url(url, timeout=timeout), distinct)))

    for row, url in candidates:
        status, code, content_type, size = results[url]
        row["url_status"] = status
        row["url_http_code"] = code
        row["url_content_type"] = content_type
        row["url_bytes"] = size
        counts[status] += 1
        if status == "dead":
            note(row, f"download_url did not resolve ({code})")
            continue
        # The URL resolves — now decide whether what came back is actually a file.
        if row.get("access_route") == "direct":
            if content_type in PAGE_TYPES:
                row["access_route"] = "portal"
                row["direct_download"] = "no"
                counts["demoted: served HTML"] += 1
                note(row, f"URL serves {content_type}, so it is a page, not a statistics file")
            elif size.isdigit() and int(size) < MIN_FILE_BYTES:
                row["access_route"] = "portal"
                row["direct_download"] = "no"
                counts["demoted: too small"] += 1
                note(row, f"URL returned only {size} bytes — not a summary-statistics file")
    write_table(destination, fields, rows)
    return counts


# ── re-screening the human-action queue ─────────────────────────────────────


def rescreen(
    source: Path, *, statuses: set[str], timeout: int, workers: int = 16
) -> Counter[str]:
    """Look again at rows parked for a person, for a public route that was missed.

    A row lands in the queue because the URL picked from its data statement was a landing
    page, a code repo or a piece of software. The statement often also names a deposit —
    a Zenodo or Figshare DOI, a BioStudies or PRIDE accession — that no link in the text
    pointed at. This re-runs the finder's picker over the stored statement with those
    patterns, and promotes a row only when the server confirms the file.
    """
    finder = _finder_module()
    fields, rows = read_table(source)
    fields = with_verify_columns(fields, rows)
    counts: Counter[str] = Counter()
    candidates: list[tuple[dict[str, str], str, str, str, str]] = []
    for row in rows:
        if row.get("verify_status", "") not in statuses:
            continue
        statement = row.get("extraction_note", "")
        if not statement:
            counts["no statement to re-read"] += 1
            continue
        url, route, direct, reason = finder.choose_url(  # type: ignore[attr-defined]
            statement, finder.URL_IN_TEXT_RE.findall(statement)  # type: ignore[attr-defined]
        )
        if not url or url == row.get("download_url", ""):
            counts["nothing new found"] += 1
            continue
        if route not in {"direct", "supplement"}:
            counts["still not public"] += 1
            continue
        candidates.append((row, url, route, direct, reason))

    distinct = list(dict.fromkeys(url for _row, url, _route, _direct, _reason in candidates))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = dict(zip(distinct, pool.map(lambda url: check_url(url, timeout=timeout), distinct)))

    for row, url, route, direct, reason in candidates:
        status, code, content_type, size = results[url]
        if status != "ok":
            counts["candidate did not resolve"] += 1
            note(row, f"re-screen: {url} did not resolve ({code})")
            continue
        # HTTP success proves only that *something* exists at the URL. It may be code,
        # raw reads, a manuscript supplement or documentation rather than association
        # statistics. Preserve it as an audit candidate; promotion requires inspecting
        # file names/contents against the paper and must never happen automatically.
        note(row, f"re-screen candidate requires semantic review: {url} ({reason})")
        counts["candidate requires semantic review"] += 1
    write_table(source, fields, rows)
    return counts


# ── unique datasets ──────────────────────────────────────────────────────────


def _finder_module() -> object:
    """Load qtl-data-finder as a module — the registry and the catalogue live there."""
    finder = Path(__file__).resolve().parents[2] / "qtl-data-finder" / "scripts" / "find_qtl.py"
    spec = importlib.util.spec_from_file_location("find_qtl", finder)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["find_qtl"] = module
    spec.loader.exec_module(module)
    return module


# A donor count in a paper's own abstract, e.g. "838 postmortem donors". Only these
# phrasings, because they name people; anything looser starts counting cells and samples.
STUDY_DONORS_RE = re.compile(
    r"([\d,]{2,7})\s+(?:postmortem\s+|unrelated\s+|healthy\s+|human\s+)?"
    r"(?:donors|individuals|participants|subjects|volunteers)",
    re.I,
)


def study_donor_count(abstract: str) -> tuple[str, str]:
    """(donor count, the sentence that says it) from a study's own abstract, or blanks.

    This is the project-level number — GTEx's 838 donors — which is a different fact from
    any single tissue's sample size, and the one a reader means by "how big is GTEx".
    """
    best: tuple[int, re.Match[str]] | None = None
    for match in STUDY_DONORS_RE.finditer(abstract):
        value = int(match.group(1).replace(",", ""))
        if 20 <= value <= 100_000 and (best is None or value > best[0]):
            best = (value, match)
    if best is None:
        return "", ""
    start = max(0, best[1].start() - 90)
    return str(best[0]), re.sub(r"\s+", " ", abstract[start : best[1].end() + 40]).strip()


def catalogue_facts() -> dict[str, dict[str, str]]:
    """For datasets the eQTL Catalogue redistributes: a verified URL and the donor count.

    This is the one place a value may be filled from outside the papers, because the
    catalogue index is first-party and `resolve` confirms the file with a HEAD request.
    Donor counts especially: the catalogue states them, where the text had to be guessed.
    """
    finder = _finder_module()
    index = finder.load_index("r7")  # type: ignore[attr-defined]
    facts: dict[str, dict[str, str]] = {}
    for name, label in finder.CATALOGUE_STUDIES.items():  # type: ignore[attr-defined]
        members = [d for d in index if d.study_label == label]
        if not members:
            continue
        # A study is many datasets — GTEx alone is 245 of them across 48 tissues, with
        # donor counts from 73 to 702. Reporting one of those as "the study's sample size"
        # is wrong: the URL points at one context, and the number belongs to that context.
        pick = max(members, key=lambda dataset: dataset.sample_size)
        try:
            found = finder.resolve(pick.study_id, pick.dataset_id)  # type: ignore[attr-defined]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            # One study's FTP hiccup must not cost the whole rollup; the row simply
            # keeps whatever the corpus gave it.
            print(f"  {name}: catalogue lookup failed ({exc})", file=sys.stderr)
            continue
        if not found.nominal:
            continue
        counts = sorted(dataset.sample_size for dataset in members)
        pmid = next((dataset.pmid for dataset in members if dataset.pmid), "")
        donors, evidence = "", ""
        if pmid:
            record = finder.epmc_records([pmid]).get(pmid, {})  # type: ignore[attr-defined]
            donors, evidence = study_donor_count(str(record.get("abstractText") or ""))
        facts[name] = {
            "study_pmid": pmid,
            "study_donors": donors,
            "study_donors_evidence": evidence[:200],
            "dataset_url": found.nominal,
            "catalogue_study": label,
            "catalogue_datasets": str(len(members)),
            "catalogue_donor_range": (
                str(counts[0]) if counts[0] == counts[-1] else f"{counts[0]}-{counts[-1]}"
            ),
            "url_dataset_id": pick.dataset_id,
            "url_dataset_context": pick.describe(),
            "url_dataset_donors": str(pick.sample_size),
        }
    return facts


def _load_registry() -> tuple[dict[str, str], frozenset[str]]:
    """Read the dataset registry from qtl-data-finder — one definition, not two."""
    finder = Path(__file__).resolve().parents[2] / "qtl-data-finder" / "scripts" / "find_qtl.py"
    namespace: dict[str, object] = {}
    source = finder.read_text(encoding="utf-8")
    start = source.index("CATALOGUES = frozenset(")
    end = source.index("# ── reading the paper ──")
    exec(compile(source[start:end], str(finder), "exec"), namespace)
    registry = namespace["QTL_DATASET_REGISTRY"]
    return (
        {name: types for name, types, _aliases in registry},  # type: ignore[misc]
        frozenset(namespace["CATALOGUES"]),  # type: ignore[arg-type]
    )


REGISTRY_TYPES, CATALOGUE_NAMES = _load_registry()


def unique_datasets(
    source: Path, destination: Path, *, use_catalogue: bool = False, verify: bool = False
) -> int:
    """Roll the reviewed papers up into one row per QTL dataset.

    A dataset is named by many papers: the one that released it, and every paper that
    later used it. The row that counts is the earliest — the same rule `dedupe` applies
    within a group — and the best access route any of them recorded.
    """
    _fields, rows = read_table(source)
    catalogue = catalogue_facts() if use_catalogue else {}
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        for name in row.get("dataset_name", "").split(";"):
            name = name.strip()
            if name:
                groups[name].append(row)

    rank = {"direct": 5, "supplement": 4, "portal": 3, "controlled": 2, "request": 1}

    def attributable(row: dict[str, str], name: str, earliest: dict[str, str]) -> bool:
        """Can this row's URL honestly be called the dataset's URL?

        A paper that merely cites GTEx still has a data statement of its own, and taking
        its URL as GTEx's is how a rollup ends up claiming CommonMind is distributed as a
        senescence gene list. Accept a URL only when it carries the dataset's own name, or
        when it comes from the earliest paper — the one that plausibly released it.
        """
        url = row.get("download_url", "")
        if not url:
            return False
        # A repo named after the dataset is the analysis code, not the dataset.
        if any(host in url.casefold() for host in ("github.com", "gitlab.com", "bitbucket.org")):
            return False
        token = re.sub(r"[^a-z0-9]+", "", name.split("/")[0].casefold())
        if len(token) > 3 and token in re.sub(r"[^a-z0-9]+", "", url.casefold()):
            return True
        # The earliest paper is the likely origin, but only its *deposits* count. Its
        # licence link, its stats software and its browser of choice are not the dataset,
        # and taking them is how deCODE ends up "distributed" by r-project.org.
        return row.get("record_id") == earliest.get("record_id") and (
            row.get("access_route") in {"direct", "supplement"}
            or (
                row.get("verify_status") == "public-access"
                and row.get("access_route") == "portal"
            )
        )

    summary: list[dict[str, str]] = []
    for name, members in sorted(groups.items(), key=lambda item: -len(item[1])):
        members.sort(key=_publication_order)
        earliest = members[0]
        candidates = [row for row in members if attributable(row, name, earliest)]
        best = (
            max(
                candidates,
                key=lambda row: (
                    row.get("url_status", "") == "ok",
                    rank.get(row.get("access_route", ""), 0),
                ),
            )
            if candidates
            else {}
        )
        # The dataset's own QTL types come from the registry; what the citing papers
        # happen to mention is a different, noisier thing and is reported separately.
        declared = REGISTRY_TYPES.get(name, "")
        mentioned = Counter(
            kind
            for row in members
            for kind in row.get("qtl_type", "").split(";")
            if kind.strip()
        )
        routes = Counter(
            row.get("access_route", "") for row in members if row.get("access_route")
        )
        entry = {
                "dataset": name,
                "papers": str(len(members)),
                "kind": "catalogue" if name in CATALOGUE_NAMES else "primary dataset",
                "qtl_types": declared,
                "types_mentioned_by_citing_papers": ";".join(
                    kind for kind, _ in mentioned.most_common()
                ),
                "earliest_paper_year": earliest.get("year", ""),
                "earliest_paper": earliest.get("publication_title", "")[:160],
                "earliest_doi": earliest.get("doi", ""),
                "earliest_pmid": earliest.get("pmid", ""),
                "dataset_url": best.get("download_url", ""),
                "dataset_url_route": best.get("access_route", ""),
                "dataset_url_status": best.get("url_status", ""),
                "url_attributed_from": best.get("record_id", ""),
                "access_routes_seen": ";".join(
                    f"{route}:{count}" for route, count in routes.most_common()
                ),
                "contexts_seen": ";".join(
                    sorted({
                        context.strip()
                        for row in members
                        for context in row.get("qtl_context", "").split(";")
                        if context.strip()
                    })
                )[:200],
        }
        entry["url_evidence"] = (
            "corpus: paper's own deposit" if entry["dataset_url"] else ""
        )
        entry.update({
            "catalogue_study": "", "catalogue_datasets": "", "catalogue_donor_range": "",
            "study_pmid": "", "study_donors": "", "study_donors_evidence": "",
            "url_dataset_id": "", "url_dataset_context": "", "url_dataset_donors": "",
        })
        if name in catalogue:
            entry.update(catalogue[name])
            entry["dataset_url_route"] = "direct"
            entry["dataset_url_status"] = "ok"
            entry["url_evidence"] = "eQTL Catalogue r7, file confirmed by HEAD"
        summary.append(entry)
    # A dataset the registry has no name for is still a dataset. Dropping those keeps the
    # rollup to famous resources and hides exactly the new releases the sweep was run to
    # find — so any row with a confirmed public data URL and no registry name gets its own
    # row here, labelled by its paper.
    named_rows = {id(row) for members in groups.values() for row in members}
    unregistered: dict[str, dict[str, str]] = {}
    for row in rows:
        if id(row) in named_rows:
            continue
        # Only rows this pipeline judged to be a QTL dataset. A public deposit alone is not
        # enough: the same filter otherwise admits tool papers, a pangenome, and the cattle
        # and plant studies the rules already rejected.
        if row.get("verify_status") not in {"verified", "public-access", "needs-request"}:
            continue
        if not row.get("qtl_type", "").strip():
            continue
        if row.get("url_status") != "ok" or row.get("access_route") not in {
            "direct", "portal", "supplement"
        }:
            continue
        url = row.get("download_url", "").strip()
        if not url or url in unregistered:
            continue
        author = row.get("first_author", "").strip() or "unattributed"
        unregistered[url] = {
            "dataset": f"{author} {row.get('year', '')}".strip(),
            "papers": "1",
            "kind": "unregistered dataset",
            "qtl_types": row.get("qtl_type", ""),
            "types_mentioned_by_citing_papers": row.get("qtl_type", ""),
            "earliest_paper_year": row.get("year", ""),
            "earliest_paper": row.get("publication_title", "")[:160],
            "earliest_doi": row.get("doi", ""),
            "earliest_pmid": row.get("pmid", ""),
            "dataset_url": url,
            "dataset_url_route": row.get("access_route", ""),
            "dataset_url_status": row.get("url_status", ""),
            "url_attributed_from": row.get("record_id", ""),
            "access_routes_seen": f"{row.get('access_route', '')}:1",
            "contexts_seen": row.get("qtl_context", "")[:200],
            "url_evidence": "this paper's own deposit, confirmed by HEAD",
            "catalogue_study": "", "catalogue_datasets": "", "catalogue_donor_range": "",
            "study_pmid": "", "study_donors": "", "study_donors_evidence": "",
            "url_dataset_id": "", "url_dataset_context": "", "url_dataset_donors": "",
        }
    summary.extend(unregistered.values())

    if verify:
        # A status carried over from whichever paper mentioned the URL is not a check of
        # this dataset's link. Ask the server directly for anything not already confirmed.
        for entry in summary:
            if entry["dataset_url"] and entry["dataset_url_status"] != "ok":
                status, code, _type, _size = check_url(entry["dataset_url"], timeout=10)
                entry["dataset_url_status"] = status
                if status == "dead":
                    entry["url_evidence"] = f"{entry['url_evidence']}; link is dead ({code})"
    write_table(destination, list(summary[0]) if summary else ["dataset"], summary)
    return len(summary)


# ── validation ───────────────────────────────────────────────────────────────


def valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def row_label(row: dict[str, str], number: int) -> str:
    identity = (
        row.get("dataset_name", "").strip()
        or row.get("publication_title", "").strip()
        or "unidentified record"
    )
    return f"row {number} (record {row.get('record_id', '?')}: {identity[:60]})"


def validate_row(row: dict[str, str], number: int, known_ids: set[str]) -> list[str]:
    errors: list[str] = []
    label = row_label(row, number)
    status = row.get("verify_status", "").strip()
    route = row.get("access_route", "").strip()
    direct = row.get("direct_download", "").strip()
    action = row.get("access_action", "").strip()

    if status not in VERIFY_STATUS:
        return [f"{label}: invalid verify_status {status!r}"]
    if status == "unresolved":
        return [f"{label}: still unresolved — every row needs a decision"]

    try:
        date.fromisoformat(row.get("verified_date", "").strip())
    except ValueError:
        errors.append(f"{label}: verified_date must be ISO YYYY-MM-DD")

    if status == "duplicate":
        target = row.get("duplicate_of", "").strip()
        if not target:
            errors.append(f"{label}: a duplicate must name the record it duplicates")
        elif target not in known_ids:
            errors.append(f"{label}: duplicate_of {target!r} is not a record in this table")
        return errors

    if status == "rejected":
        if not row.get("verifier_note", "").strip():
            errors.append(f"{label}: a rejected row must say why in verifier_note")
        return errors

    # verified and needs-request rows describe a real dataset, so the facts must be there.
    if route not in ACCESS_ROUTES or route == "unknown":
        errors.append(f"{label}: access_route must be decided, not {route!r}")
    if action not in ACCESS_ACTIONS:
        errors.append(f"{label}: invalid access_action {action!r}")
    for field in ("qtl_type", "qtl_context"):
        if not row.get(field, "").strip():
            errors.append(f"{label}: missing {field}")
    sample_size = row.get("sample_size", "").strip()
    if not sample_size.isdigit():
        errors.append(f"{label}: sample_size must be the donor count as an integer")
    elif int(sample_size) == 0:
        errors.append(f"{label}: sample_size 0 is not a checked value")

    if status == "verified":
        if direct != "yes":
            errors.append(f"{label}: verified rows are the directly downloadable ones")
        if route != "direct":
            errors.append(f"{label}: direct_download=yes conflicts with access_route={route!r}")
        if not valid_url(row.get("download_url", "").strip()):
            errors.append(f"{label}: verified rows need an HTTP(S) download_url")
        if row.get("url_status", "").strip() != "ok":
            errors.append(f"{label}: run check-urls; download_url is not confirmed to resolve")
        if action != "none":
            errors.append(f"{label}: directly downloadable data need no human action")

    if status == "public-access":
        if direct == "yes":
            errors.append(f"{label}: public-access is for a public record/bucket, not a file URL")
        if route not in PUBLIC_MANUAL_ROUTES:
            errors.append(
                f"{label}: public-access expects a portal or supplement route, not {route!r}"
            )
        if action != "open-record":
            errors.append(f"{label}: public-access must use access_action=open-record")
        if not valid_url(row.get("download_url", "").strip()):
            errors.append(f"{label}: public-access rows need the public record or bucket URL")
        if row.get("url_status", "").strip() != "ok":
            errors.append(f"{label}: public access URL has not been confirmed to resolve")

    if status == "needs-request":
        if direct == "yes":
            errors.append(f"{label}: direct_download=yes contradicts needs-request")
        if route not in NON_PUBLIC_ROUTES:
            errors.append(f"{label}: needs-request expects a non-direct access_route")
        if action in ("", "none", "open-record"):
            errors.append(f"{label}: needs-request must name the action a person has to take")
        if (
            action != "open-record"
            and not row.get("contact_email", "").strip()
            and not valid_url(row.get("download_url", "").strip())
        ):
            errors.append(
                f"{label}: record a corresponding-author address or an application/portal URL"
            )
        if not row.get("verifier_note", "").strip():
            errors.append(f"{label}: say what must be requested in verifier_note")
    return errors


def validate(source: Path, ready_out: Path | None) -> tuple[int, int]:
    fields, rows = read_table(source)
    missing = [c for c in VERIFY_COLUMNS if c not in fields]
    if missing:
        raise ValueError(
            "verification columns are missing; run dedupe first: " + ", ".join(missing)
        )
    known_ids = {row.get("record_id", "").strip() for row in rows}
    errors = [
        error
        for number, row in enumerate(rows, start=2)
        for error in validate_row(row, number, known_ids)
    ]
    if errors:
        raise ValueError("\n".join(errors))

    ready = [row for row in rows if row.get("verify_status") == "verified"]
    if ready_out is not None:
        write_table(ready_out, fields, ready)
    print("verify_status:", dict(Counter(row["verify_status"] for row in rows)))
    print("access_route :", dict(Counter(row["access_route"] for row in rows)))
    actions = Counter(row["access_action"] for row in rows if row["access_action"])
    print("access_action:", dict(actions))
    return len(rows), len(ready)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("dedupe", help="keep the earliest paper per dataset")
    p.add_argument("source", type=Path, help="review table from qtl-data-finder")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--report", type=Path, help="audit table of the duplicate groups")

    p = subparsers.add_parser("check-urls", help="confirm every download_url resolves")
    p.add_argument("source", type=Path)
    p.add_argument("--out", type=Path, help="default: edit the table in place")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--limit", type=int, default=0, help="check at most N URLs this run")
    p.add_argument("--recheck", action="store_true", help="re-check URLs already marked ok")
    p.add_argument("--workers", type=int, default=16, help="parallel URL probes (default: 16)")
    p.add_argument(
        "--routes",
        nargs="+",
        metavar="ROUTE",
        help="check only these access_route values, e.g. --routes direct supplement",
    )

    p = subparsers.add_parser(
        "rescreen", help="re-check parked rows for a public route the first pass missed"
    )
    p.add_argument("source", type=Path)
    p.add_argument(
        "--statuses", nargs="+", default=["needs-request"],
        help="which verify_status values to re-examine (default: needs-request)",
    )
    p.add_argument("--timeout", type=int, default=10)
    p.add_argument("--workers", type=int, default=16)

    p = subparsers.add_parser("datasets", help="roll the table up into one row per dataset")
    p.add_argument("source", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument(
        "--use-catalogue",
        action="store_true",
        help="fill URL and donor count from the eQTL Catalogue where it redistributes the dataset",
    )
    p.add_argument(
        "--verify-urls", action="store_true", help="HEAD every attributed URL that is not yet ok"
    )

    p = subparsers.add_parser("validate", help="enforce the review rules on every row")
    p.add_argument("source", type=Path)
    p.add_argument("--ready-out", type=Path, help="write the rows download_qtl may fetch")

    args = parser.parse_args()
    try:
        if args.command == "dedupe":
            total, kept = dedupe(args.source, args.out, args.report)
            print(
                f"grouped {total} rows into {kept} datasets; "
                f"marked {total - kept} duplicates → {args.out}"
            )
            if args.report:
                print(f"duplicate audit → {args.report}", file=sys.stderr)
        elif args.command == "check-urls":
            destination = args.out or args.source
            counts = check_urls(
                args.source,
                destination,
                timeout=args.timeout,
                limit=args.limit,
                recheck=args.recheck,
                routes=set(args.routes) if args.routes else None,
                workers=args.workers,
            )
            print(f"url_status: {dict(counts)} → {destination}")
        elif args.command == "rescreen":
            counts = rescreen(
                args.source, statuses=set(args.statuses), timeout=args.timeout,
                workers=args.workers,
            )
            print(dict(counts))
        elif args.command == "datasets":
            found = unique_datasets(
                args.source, args.out,
                use_catalogue=args.use_catalogue, verify=args.verify_urls,
            )
            print(f"{found} unique QTL datasets named across the table → {args.out}")
        else:
            total, ready = validate(args.source, args.ready_out)
            print(f"validated {total} rows; {ready} are ready to download")
            if args.ready_out:
                print(f"download-ready rows → {args.ready_out}", file=sys.stderr)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
