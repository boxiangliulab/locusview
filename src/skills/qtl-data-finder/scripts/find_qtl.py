#!/usr/bin/env python3
"""Locate QTL datasets — in catalogues first, in the literature second.

Subcommands:
  search    fuzzy-search the eQTL Catalogue index for a tissue/cell type/condition
  resolve   turn a dataset id into download URLs, verified with HEAD requests
  download  fetch resolved files, resumable, md5-checked where a checksum exists
  papers    search Europe PMC for QTL studies, with data links and author contacts
  draft     write an email requesting data that is not directly downloadable

Standard library only. `draft` never sends anything — it writes a file for a
human to review and send.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

EQTL_FTP = "https://ftp.ebi.ac.uk/pub/databases/spot/eQTL"
EQTL_META = (
    "https://raw.githubusercontent.com/eQTL-Catalogue/eQTL-Catalogue-resources"
    "/master/data_tables/dataset_metadata_{release}.tsv"
)
EQTL_POPS = (
    "https://raw.githubusercontent.com/eQTL-Catalogue/eQTL-Catalogue-resources"
    "/master/data_tables/population_assignments.tsv"
)
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
UA = "locusview-qtl-data-finder/1.0 (https://github.com/boxiangliulab/locusview)"

CACHE = Path.home() / ".cache" / "locusview-qtl-finder"

# The FTP tree a release actually lives under. `sumstats/` is r7; r8 is only
# partially published under `r8_beta/`, so a path built from the r8 table often
# 404s — see resolve(), which checks both.
TREES = {"r7": "", "r8": "r8_beta/", "r8_beta": "r8_beta/"}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+[\w]")
ACCESSION_RE = re.compile(
    r"\b(GSE\d{4,}|E-MTAB-\d+|EGA[SD]\d{6,}|phs\d{6}(?:\.v\d+\.p\d+)?|SRP\d{6,}|PRJ[END][A-Z]\d+)\b"
)


def _get(url: str, *, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return bytes(resp.read())


def _get_json(url: str) -> dict:
    return json.loads(_get(url).decode("utf-8"))


def _head_ok(url: str, *, timeout: int = 30) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError):
        return False


# ── eQTL Catalogue index ──────────────────────────────────────────────────────


@dataclass
class Dataset:
    study_id: str
    dataset_id: str
    study_label: str
    sample_group: str
    tissue_label: str
    condition_label: str
    sample_size: int
    quant_method: str
    pmid: str
    study_type: str
    release: str = ""

    def describe(self) -> str:
        cond = "" if self.condition_label in ("naive", "", "NA") else f" [{self.condition_label}]"
        return f"{self.study_label} · {self.tissue_label}{cond} · {self.quant_method}"


def load_index(release: str = "r7", *, refresh: bool = False) -> list[Dataset]:
    """Load the eQTL Catalogue dataset table, cached under ~/.cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"dataset_metadata_{release}.tsv"
    if refresh or not path.exists():
        path.write_bytes(_get(EQTL_META.format(release=release)))
    rows: list[Dataset] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            rows.append(
                Dataset(
                    study_id=row["study_id"],
                    dataset_id=row["dataset_id"],
                    study_label=row["study_label"],
                    sample_group=row.get("sample_group", ""),
                    tissue_label=row.get("tissue_label", ""),
                    condition_label=row.get("condition_label", ""),
                    sample_size=int(row.get("sample_size") or 0),
                    quant_method=row.get("quant_method", ""),
                    pmid=row.get("pmid", ""),
                    study_type=row.get("study_type", ""),
                    release=release,
                )
            )
    return rows


def score(query: str, dataset: Dataset) -> float:
    """Best similarity between the query and any of the dataset's names."""
    q = query.lower()
    fields = [
        dataset.tissue_label,
        dataset.sample_group,
        dataset.study_label,
        dataset.condition_label,
        f"{dataset.tissue_label} {dataset.condition_label}",
    ]
    best = 0.0
    for field in fields:
        text = (field or "").lower().replace("_", " ")
        if not text:
            continue
        if q in text or text in q:
            best = max(best, 0.95)
        best = max(best, difflib.SequenceMatcher(None, q, text).ratio())
    return best


def search(
    query: str, release: str, *, quant: str | None, min_n: int, limit: int
) -> list[tuple[float, Dataset]]:
    hits = []
    for dataset in load_index(release):
        if quant and dataset.quant_method != quant:
            continue
        if dataset.sample_size < min_n:
            continue
        value = score(query, dataset)
        if value >= 0.55:
            hits.append((value, dataset))
    hits.sort(key=lambda pair: (-pair[0], -pair[1].sample_size))
    return hits[:limit]


# ── study-level population and the shared metadata store ─────────────────────

# A study is labelled with one population only when that group clearly dominates;
# otherwise it is ALL. GTEx is 705/838 European (0.84) and correctly comes out ALL,
# while Alasoo_2018 at 83/84 (0.99) comes out EUR.
POPULATION_DOMINANCE = 0.9


def load_populations(*, refresh: bool = False) -> dict[str, str]:
    """study_label → population code, from the catalogue's ancestry counts."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "population_assignments.tsv"
    if refresh or not path.exists():
        path.write_bytes(_get(EQTL_POPS))
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            study = row.get("Study", "")
            try:
                total = float(row.get("Sample Size") or 0)
            except ValueError:
                continue
            if not study or total <= 0:
                continue
            counts = {}
            for code in ("EUR", "AFR", "SAS", "EAS"):
                try:
                    counts[code] = float(row.get(code) or 0)
                except ValueError:
                    counts[code] = 0.0
            best = max(counts, key=lambda c: counts[c])
            out[study] = best if counts[best] / total >= POPULATION_DOMINANCE else "ALL"
    return out


def metadata_record(dataset: Dataset, found: Resolved, population: str) -> dict:
    """The fields sumstats-manifest needs but cannot read out of a data file."""
    single_cell = dataset.study_type == "single-cell"
    # The catalogue publishes expression and splicing phenotypes side by side;
    # which one a file holds is decided by quant_method, not by the study.
    qtl_type = "sQTL" if dataset.quant_method in ("leafcutter", "txrev") else "eQTL"
    return {
        "kind": "qtl",
        "key": f"{dataset.study_label}|{qtl_type}|{dataset.sample_group}",
        "dataset": dataset.study_label,
        "qtl_type": qtl_type,
        "biocontext": dataset.sample_group,
        "level_1_context": dataset.tissue_label,
        "level_2_context": dataset.sample_group if single_cell else "",
        "population": population,
        "sample_size": dataset.sample_size,
        "url": f"https://www.ebi.ac.uk/eqtl/Studies/#{dataset.study_id}",
        "download_url": found.nominal,
        "provenance": {
            "source": f"eQTL Catalogue {dataset.release} metadata table",
            "fetched": date.today().isoformat(),
            "dataset_id": dataset.dataset_id,
            "study_id": dataset.study_id,
            "quant_method": dataset.quant_method,
            "study_type": dataset.study_type,
            "pmid": dataset.pmid,
            "population_from": (
                "population_assignments.tsv ancestry counts"
                if population
                else "NOT AVAILABLE — study absent from population_assignments.tsv, fill in by hand"
            ),
        },
    }


def save_metadata(path: Path, record: dict) -> str:
    """Upsert one record into the shared JSONL store, keyed on kind + key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if path.exists():
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    ident = (record["kind"], record["key"])
    action = "added"
    for i, existing in enumerate(rows):
        if (existing.get("kind"), existing.get("key")) == ident:
            rows[i] = record
            action = "updated"
            break
    else:
        rows.append(record)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    return action


# ── resolving download URLs ───────────────────────────────────────────────────


@dataclass
class Resolved:
    dataset_id: str
    tree: str = ""
    nominal: str = ""
    nominal_index: str = ""
    permuted: str = ""
    credible_sets: str = ""
    lbf: str = ""
    note: str = ""


def resolve(study_id: str, dataset_id: str) -> Resolved:
    """Build and verify FTP URLs, trying each release tree.

    The path template is deterministic, but a dataset listed in the metadata
    table is not necessarily published yet — r8 rows routinely 404 under both
    trees. Every URL returned here has been confirmed with a HEAD request.
    """
    for label, prefix in (("r7", ""), ("r8_beta", "r8_beta/")):
        base = f"{EQTL_FTP}/{prefix}sumstats/{study_id}/{dataset_id}/{dataset_id}"
        if not _head_ok(f"{base}.all.tsv.gz"):
            continue
        susie = f"{EQTL_FTP}/{prefix}susie/{study_id}/{dataset_id}/{dataset_id}"
        out = Resolved(dataset_id=dataset_id, tree=label, nominal=f"{base}.all.tsv.gz")
        for attr, url in (
            ("nominal_index", f"{base}.all.tsv.gz.tbi"),
            ("permuted", f"{base}.permuted.tsv.gz"),
            ("credible_sets", f"{susie}.credible_sets.tsv.gz"),
            ("lbf", f"{susie}.lbf_variable.txt.gz"),
        ):
            if _head_ok(url):
                setattr(out, attr, url)
        return out
    return Resolved(
        dataset_id=dataset_id,
        note="listed in the metadata table but not published on the FTP site yet",
    )


# ── downloading ───────────────────────────────────────────────────────────────


def download(url: str, dest_dir: Path, *, expect_md5: str | None = None) -> Path:
    """Resumable download. Re-running skips files that are already complete."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / url.rsplit("/", 1)[-1]
    have = dest.stat().st_size if dest.exists() else 0

    headers = {"User-Agent": UA}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            mode = "ab" if resp.status == 206 else "wb"
            with dest.open(mode) as fh:
                while chunk := resp.read(1 << 20):
                    fh.write(chunk)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and have:  # already complete
            return dest
        raise

    if expect_md5:
        digest = hashlib.md5(dest.read_bytes()).hexdigest()
        if digest != expect_md5:
            raise RuntimeError(f"md5 mismatch for {dest.name}: {digest} != {expect_md5}")
    return dest


# ── literature ────────────────────────────────────────────────────────────────


@dataclass
class Paper:
    pmid: str
    doi: str
    title: str
    journal: str
    year: str
    authors: str
    is_open_access: bool
    has_data: bool
    accessions: list[str]
    emails: list[str]
    urls: list[str]

    def citation(self) -> str:
        return f"{self.authors.split(',')[0]} et al. ({self.year}) {self.journal}"


def _paper_from(raw: dict) -> Paper:
    affiliations = " ".join(
        aff.get("affiliation", "")
        for author in ((raw.get("authorList") or {}).get("author") or [])
        for aff in (
            (author.get("authorAffiliationDetailsList") or {}).get("authorAffiliation") or []
        )
    )
    text = " ".join([raw.get("abstractText") or "", affiliations])
    urls = [
        u.get("url", "")
        for u in ((raw.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
        if u.get("url")
    ]
    return Paper(
        pmid=str(raw.get("pmid") or ""),
        doi=str(raw.get("doi") or ""),
        title=(raw.get("title") or "").strip(),
        journal=str(raw.get("journalTitle") or ""),
        year=str(raw.get("pubYear") or ""),
        authors=str(raw.get("authorString") or ""),
        is_open_access=str(raw.get("isOpenAccess") or "N") == "Y",
        has_data=str(raw.get("hasData") or "N") == "Y",
        accessions=sorted(set(ACCESSION_RE.findall(text))),
        emails=sorted(set(EMAIL_RE.findall(affiliations))),
        urls=urls[:3],
    )


def papers(query: str, *, limit: int) -> list[Paper]:
    """Search Europe PMC for QTL papers.

    Emails come from the affiliation strings, where PubMed puts the
    corresponding author's address — there is no dedicated contact field.
    """
    full = f"({query}) AND (QTL OR eQTL OR sQTL OR pQTL OR caQTL)"
    args = {"query": full, "format": "json", "pageSize": limit, "resultType": "core"}
    data = _get_json(f"{EPMC}?{urllib.parse.urlencode(args)}")
    return [_paper_from(r) for r in (data.get("resultList") or {}).get("result", [])]


# ── email drafting ────────────────────────────────────────────────────────────

TEMPLATE = """\
To: {to}
Subject: {subject}

Dear {salutation},

I am writing from the Boxiang Liu lab at the National University of Singapore. We
maintain locusview (https://github.com/boxiangliulab/locusview), an open resource
that aggregates publicly available QTL datasets so researchers can browse and
compare them alongside GWAS signals.

We would like to include the {data_kind} from:

    {citation}
    {title}
    {reference}

{reason}

Would you be willing to share the summary statistics, or point us to a location
where we can obtain them? To be explicit about how they would be used:

  - we would host the summary statistics, with your study credited and cited on
    every page and download that draws on it;
  - we would follow any embargo, licence, or attribution terms you specify;
  - we would not redistribute individual-level data of any kind.

If a data-transfer agreement or formal request process is required, we are glad
to follow it. Thank you for considering this, and for making the work available.

With thanks,

{sender}
"""


def draft_email(
    *,
    to: str,
    citation: str,
    title: str,
    reference: str,
    reason: str,
    data_kind: str,
    sender: str,
    salutation: str,
) -> str:
    subject = f"Request: {data_kind} from {citation} for the locusview QTL resource"
    return TEMPLATE.format(
        to=to or "TODO — corresponding author address",
        subject=subject,
        salutation=salutation,
        data_kind=data_kind,
        citation=citation,
        title=textwrap.shorten(title, 100, placeholder="…"),
        reference=reference,
        reason=textwrap.fill(reason, 76),
        sender=sender,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────


def cmd_search(args: argparse.Namespace) -> int:
    hits = search(args.query, args.release, quant=args.quant, min_n=args.min_n, limit=args.top)
    if not hits:
        print(f"nothing in the {args.release} index matched {args.query!r}", file=sys.stderr)
        print("try `papers` to look for an unpublished-to-catalogue dataset", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([asdict(d) | {"score": round(s, 3)} for s, d in hits], indent=2))
        return 0
    print(f"  {'dataset':<12} {'study':<10} {'N':>6}  {'quant':<6} description")
    for value, d in hits:
        print(
            f"  {d.dataset_id:<12} {d.study_id:<10} {d.sample_size:>6}  "
            f"{d.quant_method:<6} {d.describe()}   ({value:.2f})"
        )
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    index = {d.dataset_id: d for d in load_index(args.release)}
    dataset = index.get(args.dataset_id)
    if dataset is None:
        print(f"{args.dataset_id} is not in the {args.release} index", file=sys.stderr)
        return 1
    found = resolve(dataset.study_id, dataset.dataset_id)
    if args.json:
        print(json.dumps(asdict(dataset) | {"files": asdict(found)}, indent=2))
        return 0
    print(f"{dataset.dataset_id}  {dataset.describe()}  (N={dataset.sample_size})")
    if args.save_metadata:
        # Only 27 of the 42 r7 studies appear in population_assignments.tsv.
        # Leaving the rest blank makes the gap visible instead of asserting ALL.
        population = load_populations().get(dataset.study_label, "")
        record = metadata_record(dataset, found, population)
        action = save_metadata(args.save_metadata, record)
        if not population:
            print(
                f"  WARNING: no ancestry data for {dataset.study_label}; "
                f"population left blank — set it from the paper before loading"
            )
        print(
            f"metadata {action} in {args.save_metadata}: {record['dataset']} · "
            f"{record['qtl_type']} · {record['biocontext']} · {record['population']} · "
            f"N={record['sample_size']}"
        )
    if found.note:
        print(f"  {found.note}")
        return 1
    print(f"  tree: {found.tree}")
    for label in ("nominal", "nominal_index", "permuted", "credible_sets", "lbf"):
        url = getattr(found, label)
        if url:
            print(f"  {label:<14} {url}")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    index = {d.dataset_id: d for d in load_index(args.release)}
    dataset = index.get(args.dataset_id)
    if dataset is None:
        print(f"{args.dataset_id} is not in the {args.release} index", file=sys.stderr)
        return 1
    found = resolve(dataset.study_id, dataset.dataset_id)
    if found.note:
        print(f"cannot download: {found.note}", file=sys.stderr)
        return 1
    wanted = (
        ["nominal", "nominal_index"]
        if not args.all_files
        else ["nominal", "nominal_index", "permuted", "credible_sets", "lbf"]
    )
    for label in wanted:
        url = getattr(found, label)
        if not url:
            continue
        dest = download(url, args.out / dataset.dataset_id)
        print(f"  {label:<14} {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return 0


def cmd_papers(args: argparse.Namespace) -> int:
    found = papers(args.query, limit=args.top)
    if args.json:
        print(json.dumps([asdict(p) for p in found], indent=2))
        return 0
    for p in found:
        flags = ",".join(
            f for f, on in (("open-access", p.is_open_access), ("has-data", p.has_data)) if on
        )
        print(f"\n{p.citation()}  [{flags or 'no data flags'}]")
        print(f"  {textwrap.shorten(p.title, 96, placeholder='…')}")
        print(f"  pmid {p.pmid or '—'}  doi {p.doi or '—'}")
        if p.accessions:
            print(f"  accessions : {', '.join(p.accessions)}")
        if p.emails:
            print(f"  contact    : {', '.join(p.emails)}")
        for url in p.urls:
            print(f"  fulltext   : {url}")
    return 0


def cmd_draft(args: argparse.Namespace) -> int:
    body = draft_email(
        to=args.to,
        citation=args.citation,
        title=args.title,
        reference=args.reference,
        reason=args.reason,
        data_kind=args.data_kind,
        sender=args.sender,
        salutation=args.salutation,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8")
        print(f"draft written to {args.out}", file=sys.stderr)
        print("REVIEW IT, then send it yourself — this tool does not send mail.", file=sys.stderr)
    else:
        print(body)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_release(p: argparse.ArgumentParser) -> None:
        p.add_argument("--release", default="r7", choices=["r7", "r8", "r8_beta"])

    s = sub.add_parser("search", help="fuzzy-search the eQTL Catalogue index")
    s.add_argument("query", help='tissue, cell type or condition, e.g. "pancreatic islet"')
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--quant", help="ge, exon, tx, txrev, leafcutter, aptamer, microarray")
    s.add_argument("--min-n", type=int, default=0, help="minimum sample size")
    s.add_argument("--json", action="store_true")
    add_release(s)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("resolve", help="dataset id → verified download URLs")
    s.add_argument("dataset_id", help="e.g. QTD000001")
    s.add_argument("--json", action="store_true")
    s.add_argument(
        "--save-metadata",
        type=Path,
        help="upsert this dataset into a shared metadata store (JSONL) for sumstats-manifest",
    )
    add_release(s)
    s.set_defaults(func=cmd_resolve)

    s = sub.add_parser("download", help="download a dataset's files")
    s.add_argument("dataset_id")
    s.add_argument("--out", type=Path, default=Path("data/qtl"))
    s.add_argument("--all-files", action="store_true", help="also permuted + SuSiE outputs")
    add_release(s)
    s.set_defaults(func=cmd_download)

    s = sub.add_parser("papers", help="search Europe PMC for QTL studies")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_papers)

    s = sub.add_parser("draft", help="write a data-request email (does NOT send)")
    s.add_argument("--to", default="", help="corresponding author address")
    s.add_argument("--citation", required=True, help='e.g. "Smith et al. (2024) Nat Genet"')
    s.add_argument("--title", required=True)
    s.add_argument("--reference", default="", help="DOI or PMID line")
    s.add_argument("--data-kind", default="QTL summary statistics")
    s.add_argument(
        "--reason",
        default="We were unable to find these summary statistics in a public repository.",
    )
    s.add_argument("--salutation", default="Dr.")
    s.add_argument("--sender", default="TODO — your name, title, affiliation")
    s.add_argument("--out", type=Path, help="write the draft here instead of stdout")
    s.set_defaults(func=cmd_draft)

    args = ap.parse_args()
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
