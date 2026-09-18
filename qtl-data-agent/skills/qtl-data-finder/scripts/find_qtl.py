#!/usr/bin/env python3
"""Find published QTL datasets in the literature, and write the review table.

Subcommands:
  review    keyword sweep of Europe PMC across QTL query families → qtlliteraturereview TSV
  papers    one ad-hoc Europe PMC query, printed or appended to a review table
  update    record what reading a paper established (download URL, context, sample size…)
  search    fuzzy-search the eQTL Catalogue index for a tissue/cell type/condition
  resolve   turn a catalogue dataset id into verified download URLs
  draft     write an email requesting data that is not directly downloadable

Stage 1 of the pipeline. `review` collects candidates; `update` is how a candidate
becomes a dataset row with a download URL. Verification, downloading and manifest
registration belong to the qtl-record-verifier, download_qtl and sumstats-manifest
skills. Standard library only; `draft` never sends anything.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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

QTL_TYPE_PATTERNS = (
    ("caQTL", re.compile(r"\b(?:caqtl|chromatin accessibility qtl|accessibility qtl)s?\b", re.I)),
    ("sQTL", re.compile(r"\b(?:sqtl|splicing qtl|splice qtl)s?\b", re.I)),
    ("pQTL", re.compile(r"\b(?:pqtl|protein qtl|proteomic qtl)s?\b", re.I)),
    ("meQTL", re.compile(r"\b(?:meqtl|methylation qtl)s?\b", re.I)),
    ("hQTL", re.compile(r"\b(?:hqtl|histone qtl|histone modification qtl)s?\b", re.I)),
    ("metabolite-QTL", re.compile(r"\b(?:metabolite|metabolic) qtl(s)?\b", re.I)),
    ("eQTL", re.compile(r"\b(?:eqtl|expression qtl)s?\b", re.I)),
)

# Keyword families for the literature sweep. Each family is a separate Europe PMC
# query; results are merged and deduplicated on PMID/DOI. Families exist because a
# single query cannot reach both "the newest release" and "the largest cohort".
REVIEW_TERM_FAMILIES: dict[str, tuple[str, ...]] = {
    "molecular-type": (
        "eQTL OR expression quantitative trait loci",
        '"trans eQTL" OR "trans expression quantitative trait loci"',
        "sQTL OR splicing quantitative trait loci",
        "pQTL OR protein quantitative trait loci",
        "caQTL OR chromatin accessibility quantitative trait loci",
        "meQTL OR methylation quantitative trait loci",
        "hQTL OR histone quantitative trait loci",
        '"metabolite QTL" OR "metabolic QTL" OR mQTL',
        '"lipid QTL" OR lipidomic QTL',
        'riboQTL OR "translation QTL" OR "microRNA QTL" OR miQTL',
        '"allele-specific" QTL OR molecular QTL OR molQTL',
    ),
    "single-cell": (
        '"single cell" QTL OR "single-cell" QTL OR scQTL OR "sc-eQTL"',
        '"cell type specific" QTL OR "cell-type-specific" QTL OR "cell type resolved" QTL',
        'pseudobulk QTL OR "cell state" QTL OR "cell-state" QTL',
        '"single nucleus" QTL OR "single-nucleus" QTL OR snRNA-seq QTL',
        'OneK1K OR DICE OR "single-cell eQTLGen" OR sc-eQTLGen',
    ),
    "context": (
        'context QTL OR "context specific" QTL OR "context-dependent" QTL',
        'response QTL OR reQTL OR "dynamic QTL" OR "interaction QTL"',
        '"stimulation" QTL OR "treatment" QTL OR "infection" QTL OR "activation" QTL',
        '"disease state" QTL OR "case control" QTL OR "tumor" QTL OR "tumour" QTL',
        '"developmental" QTL OR "differentiation" QTL OR "time course" QTL',
        'QTL AND (tissue OR "cell type" OR organ OR "brain region")',
    ),
    "new-release": (
        'QTL AND ("we present" OR "we report" OR "here we describe") AND '
        '("resource" OR "atlas" OR "catalogue" OR "catalog")',
        'QTL AND ("new dataset" OR "newly generated" OR "data release" OR "release of")',
        'QTL AND ("summary statistics" AND ("are available" OR "have been deposited"))',
        '"QTL atlas" OR "QTL resource" OR "QTL browser" OR "QTL portal"',
    ),
    "large-sample": (
        'QTL AND ("largest" OR "large-scale" OR "large scale") AND (cohort OR biobank)',
        'QTL AND (biobank OR "UK Biobank" OR consortium OR meta-analysis)',
        'QTL AND ("sample size" OR "n =" OR donors) AND (thousand OR "1,000" OR "10,000")',
        'eQTLGen OR GTEx OR "Genotype-Tissue Expression" OR MetaBrain OR PsychENCODE',
    ),
}
# The organism scope every family is ANDed with. "human OR Homo sapiens" alone is far too
# narrow — measured against the eQTL family it returns 964 papers where this returns 4,000+,
# because most human QTL papers never write either phrase; they write donors, cohort, patients.
HUMAN_SCOPE = (
    'human OR "Homo sapiens" OR patients OR donors OR individuals OR cohort OR biobank '
    "OR blood OR brain OR tissue"
)

REVIEW_TERM_FAMILIES["all"] = tuple(
    term for family in REVIEW_TERM_FAMILIES.values() for term in family
)


def _get(url: str, *, timeout: int = 90, attempts: int = 3) -> bytes:
    """Retry with backoff: these APIs throttle, and a swallowed 429 empties a whole batch."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return bytes(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                raise
            last = exc
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last if last else RuntimeError(f"request failed: {url}")


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
    qtl_types: list[str]
    matched_terms: list[str]

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
    text = " ".join([raw.get("title") or "", raw.get("abstractText") or "", affiliations])
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
        qtl_types=[label for label, pattern in QTL_TYPE_PATTERNS if pattern.search(text)],
        matched_terms=[],
    )


PAGE_SIZE = 1000  # Europe PMC's per-request maximum.


def papers(query: str, *, limit: int) -> list[Paper]:
    """Search Europe PMC for QTL papers, paging past the 1,000-result-per-request cap.

    Emails come from the affiliation strings, where PubMed puts the
    corresponding author's address — there is no dedicated contact field.

    A single request returns at most 1,000 hits however large `limit` is, which is why
    recall stalls without `cursorMark`: the second thousand of a 20,000-hit query is
    unreachable, and the queries that matter here all exceed that.
    """
    full = f"({query}) AND (QTL OR eQTL OR sQTL OR pQTL OR caQTL)"
    found: list[Paper] = []
    cursor = "*"
    while len(found) < limit:
        args = {
            "query": full,
            "format": "json",
            "pageSize": min(PAGE_SIZE, limit - len(found)),
            "resultType": "core",
            "cursorMark": cursor,
        }
        data = _get_json(f"{EPMC}?{urllib.parse.urlencode(args)}")
        batch = (data.get("resultList") or {}).get("result", [])
        found.extend(_paper_from(raw) for raw in batch)
        next_cursor = str(data.get("nextCursorMark") or "")
        # Europe PMC repeats the cursor on the last page instead of omitting it.
        if not batch or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return found


def _paper_key(paper: Paper) -> str:
    """Stable-enough paper identity for merging results from overlapping survey queries."""
    if paper.pmid:
        return f"pmid:{paper.pmid}"
    if paper.doi:
        return f"doi:{paper.doi.lower()}"
    return "title:" + re.sub(r"\W+", "", paper.title.lower())


def sweep(query: str, families: tuple[str, ...], *, top_per_query: int) -> list[Paper]:
    """Run every query family and merge the hits, deduplicated on PMID/DOI."""
    found: dict[str, Paper] = {}
    for family in families:
        for term in REVIEW_TERM_FAMILIES[family]:
            for paper in papers(f"({query}) AND ({term})", limit=top_per_query):
                key = _paper_key(paper)
                if key not in found:
                    paper.matched_terms = [family]
                    found[key] = paper
                    continue
                existing = found[key]
                existing.matched_terms = sorted(set(existing.matched_terms) | {family})
                existing.qtl_types = sorted(set(existing.qtl_types) | set(paper.qtl_types))
                existing.accessions = sorted(set(existing.accessions) | set(paper.accessions))
                existing.emails = sorted(set(existing.emails) | set(paper.emails))
                existing.urls = list(dict.fromkeys(existing.urls + paper.urls))[:6]
    return sorted(found.values(), key=lambda p: (p.year, p.title), reverse=True)


# ── the review table ─────────────────────────────────────────────────────────
#
# One table carries a dataset from literature hit to registered manifest row.
# This skill owns the first block of columns; qtl-record-verifier, download_qtl
# and sumstats-manifest each append their own block and never rewrite this one,
# except where the verifier corrects a value it checked against the paper.

REVIEW_COLUMNS = (
    "record_id",
    "publication_title",
    "publication_url",
    "doi",
    "pmid",
    "first_author",
    "authors",
    "year",
    "journal",
    "contact_email",
    "qtl_type",
    "qtl_context",
    "population",
    "sample_size",
    "dataset_name",
    "download_url",
    "access_route",
    "direct_download",
    "extraction_note",
    "evidence_source",
    "search_terms",
    "search_date",
)

ACCESS_ROUTES = (
    "direct", "portal", "supplement", "controlled", "request", "blocked", "unavailable",
    "unknown",
)
DIRECT_DOWNLOAD = ("yes", "no", "unknown")

# Hosts that only ever serve the article, never the statistics.
PUBLICATION_HOSTS = frozenset({
    "doi.org", "dx.doi.org", "pubmed.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov",
    "europepmc.org", "www.europepmc.org", "pmc.ncbi.nlm.nih.gov",
})

# Fields `update` may set: everything a person or agent learns by reading the paper.
UPDATABLE = (
    "contact_email", "qtl_type", "qtl_context", "population", "sample_size",
    "dataset_name", "download_url", "access_route", "direct_download", "extraction_note",
    "evidence_source",
)


def review_table_path(out: Path | None, search_date: str) -> Path:
    """Default name is qtlliteraturereview-<search date>.tsv, per the pipeline convention."""
    return out if out is not None else Path(f"qtlliteraturereview-{search_date}.tsv")


def read_review_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    delimiter = "," if path.suffix.casefold() == ".csv" else "\t"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    if not fields:
        raise ValueError(f"table has no header: {path}")
    return fields, rows


def write_review_table(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    delimiter = "," if path.suffix.casefold() == ".csv" else "\t"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def _publication_url(paper: Paper) -> str:
    if paper.doi:
        return f"https://doi.org/{paper.doi}"
    if paper.pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/"
    return paper.urls[0] if paper.urls else ""


def review_row(paper: Paper, record_id: int, search_date: str) -> dict[str, str]:
    """One literature hit as a review row. Everything the full text must supply is blank."""
    return {
        "record_id": str(record_id),
        "publication_title": paper.title,
        "publication_url": _publication_url(paper),
        "doi": paper.doi,
        "pmid": paper.pmid,
        "first_author": paper.authors.split(",")[0].strip(),
        "authors": paper.authors,
        "year": paper.year,
        "journal": paper.journal,
        # Europe PMC has no contact field; this is the address in the affiliation string.
        "contact_email": ";".join(paper.emails),
        "qtl_type": ";".join(paper.qtl_types),
        "qtl_context": "",
        "population": "",
        "sample_size": "",
        "dataset_name": "",
        "download_url": "",
        "access_route": "unknown",
        "direct_download": "unknown",
        "extraction_note": "",
        "evidence_source": "",
        "search_terms": ";".join(paper.matched_terms),
        "search_date": search_date,
    }


def write_review(path: Path, found: list[Paper], search_date: str) -> int:
    rows = [review_row(paper, index, search_date) for index, paper in enumerate(found, start=1)]
    write_review_table(path, list(REVIEW_COLUMNS), rows)
    return len(rows)


def append_review(path: Path, found: list[Paper], search_date: str) -> int:
    """Add hits to an existing table, skipping papers it already lists."""
    fields, rows = read_review_table(path)
    seen = {
        value.casefold()
        for row in rows
        for value in (row.get("doi", ""), row.get("pmid", ""), row.get("publication_title", ""))
        if value
    }
    next_id = max((int(row["record_id"]) for row in rows if row.get("record_id", "").isdigit()),
                  default=0) + 1
    added = 0
    for paper in found:
        keys = {value.casefold() for value in (paper.doi, paper.pmid, paper.title) if value}
        if keys & seen:
            continue
        rows.append(review_row(paper, next_id, search_date))
        seen |= keys
        next_id += 1
        added += 1
    write_review_table(path, fields, rows)
    return added


def update_record(path: Path, record_id: str, assignments: list[str]) -> dict[str, str]:
    """Write what reading the paper established into one row, with the values checked."""
    fields, rows = read_review_table(path)
    row = next((r for r in rows if r.get("record_id") == record_id), None)
    if row is None:
        raise ValueError(f"no record_id {record_id!r} in {path}")
    for assignment in assignments:
        field, separator, value = assignment.partition("=")
        field, value = field.strip(), value.strip()
        if not separator or field not in UPDATABLE:
            raise ValueError(
                f"cannot set {field!r}; updatable fields are: {', '.join(UPDATABLE)}"
            )
        if field == "access_route" and value not in ACCESS_ROUTES:
            raise ValueError(f"access_route must be one of: {', '.join(ACCESS_ROUTES)}")
        if field == "direct_download" and value not in DIRECT_DOWNLOAD:
            raise ValueError(f"direct_download must be one of: {', '.join(DIRECT_DOWNLOAD)}")
        if field == "sample_size" and value and not value.isdigit():
            raise ValueError("sample_size must be the donor count as a plain integer")
        if field == "download_url" and value:
            if not value.startswith(("http://", "https://")):
                raise ValueError("download_url must be an HTTP(S) URL to the statistics file")
            host = urllib.parse.urlparse(value).netloc.casefold()
            # The commonest wrong value: the article itself. That is publication_url.
            if host in PUBLICATION_HOSTS:
                raise ValueError(
                    f"{host} is a publication page, not summary statistics; "
                    "download_url takes the association-statistics file"
                )
        row[field] = value
    if row.get("download_url") and row.get("access_route") == "unknown":
        raise ValueError("set access_route when you record a download_url")
    write_review_table(path, fields, rows)
    return row


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


# ── the QTL dataset registry ─────────────────────────────────────────────────
#
# Which QTL dataset a paper used is almost never in a structured field: it is a name
# in the Methods. Matching those names is what turns a pile of papers into a list of
# datasets, and it is what makes `qtl-record-verifier dedupe` work at all, because its
# identity key starts with dataset_name.
#
# Each entry is (canonical name, QTL types, alias patterns), matched case-insensitively
# against title, abstract and data statement — except acronyms, wrapped in `(?-i:...)`,
# because a case-insensitive \bMESA\b also matches "mesa" and a bare INTERVAL matches
# the English word. Both mistakes file real papers under the wrong dataset.
#
# CATALOGUES redistribute other people's QTL statistics. They are worth finding, but
# they are not new datasets, and counting them beside primary studies overstates both.

CATALOGUES = frozenset({
    "eQTL Catalogue", "QTLbase", "PhenoScanner", "Open Targets Genetics", "IEU OpenGWAS",
    "SMR data portal", "scQTLbase", "mQTLdb", "GTExPortal single-cell",
})

QTL_DATASET_REGISTRY: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # bulk tissue eQTL
    ("GTEx", "eQTL;sQTL", (r"GTEx", r"Genotype[- ]Tissue Expression")),
    ("eQTLGen", "eQTL", (r"eQTLGen",)),
    ("MetaBrain", "eQTL;sQTL", (r"MetaBrain",)),
    ("PsychENCODE", "eQTL;sQTL", (r"PsychENCODE", r"Psych ?ENCODE")),
    ("CommonMind", "eQTL;sQTL", (r"CommonMind", r"(?-i:\bCMC\b)")),
    ("BrainSeq", "eQTL;sQTL", (r"BrainSeq",)),
    ("ROSMAP", "eQTL;meQTL", (r"ROSMAP", r"Religious Orders Study")),
    ("Braineac/UKBEC", "eQTL", (r"Braineac", r"UKBEC", r"UK Brain Expression")),
    ("GEUVADIS", "eQTL;sQTL", (r"GEUVADIS",)),
    ("TwinsUK/MuTHER", "eQTL;meQTL", (r"MuTHER", r"TwinsUK")),
    ("BIOS", "eQTL;meQTL", (r"(?-i:\bBIOS\b) consortium", r"Biobank-based Integrative Omics")),
    ("DGN", "eQTL", (r"Depression Genes and Networks", r"(?-i:\bDGN\b)")),
    ("STARNET", "eQTL", (r"STARNET",)),
    ("Framingham (FHS)", "eQTL;meQTL", (r"Framingham",)),
    ("MESA", "eQTL;meQTL", (r"(?-i:\bMESA\b)", r"Multi-Ethnic Study of Atherosclerosis")),
    ("GENOA", "eQTL", (r"(?-i:\bGENOA\b)", r"Genetic Epidemiology Network of Arteriopathy")),
    ("Young Finns", "eQTL", (r"Young Finns",)),
    ("NTR/NESDA", "eQTL", (r"Netherlands Twin Register", r"(?-i:\bNESDA\b)")),
    ("CEDAR", "eQTL", (r"(?-i:\bCEDAR\b)",)),
    ("LIFE-Heart", "eQTL", (r"LIFE-Heart",)),
    ("TOPMed", "eQTL", (r"TOPMed", r"Trans-Omics for Precision Medicine")),
    # immune and sorted cell types
    # A bare DICE also names the Dutch-Icelandic migraine consortium, so it needs a
    # disambiguating word. Any generic acronym in this registry needs the same.
    ("DICE", "eQTL",
     (r"(?-i:\bDICE\b) ?(?:database|project|data|resource|eQTLs?)",
      r"Database of Immune Cell Expression")),
    ("BLUEPRINT", "eQTL;meQTL;hQTL", (r"BLUEPRINT",)),
    ("ImmuNexUT", "eQTL", (r"ImmuNexUT", r"Immune Cell Gene Expression Atlas")),
    ("Fairfax monocyte", "eQTL", (r"Fairfax",)),
    ("Alasoo macrophage", "eQTL;caQTL;tuQTL", (r"Alasoo", r"macrophage tuQTL")),
    ("Nedelec/Quach macrophage", "eQTL", (r"Nedelec", r"Nédélec", r"Quach")),
    ("Schmiedel", "eQTL", (r"Schmiedel",)),
    ("Kasela", "eQTL", (r"Kasela",)),
    # single cell
    ("OneK1K", "eQTL", (r"OneK1K", r"One ?K1K", r"Yazar")),
    ("sc-eQTLGen", "eQTL", (r"sc-?eQTLGen", r"single-cell eQTLGen")),
    ("TenK10K", "eQTL;caQTL", (r"TenK10K",)),
    ("CLUES/Perez lupus", "eQTL", (r"(?-i:\bCLUES\b)",)),
    ("van der Wijst", "eQTL", (r"van der Wijst",)),
    ("Randolph influenza", "eQTL", (r"Randolph",)),
    ("CIMA", "eQTL;caQTL", (r"(?-i:\bCIMA\b)",)),
    ("IBDVerse", "eQTL", (r"IBDVerse", r"ibdverse")),
    # pQTL
    ("UKB-PPP", "pQTL", (r"UKB-?PPP", r"UK Biobank Pharma Proteomics")),
    ("deCODE plasma pQTL", "pQTL", (r"deCODE", r"Ferkingstad")),
    ("INTERVAL/SomaLogic", "pQTL",
     (r"(?-i:\bINTERVAL\b) (?:study|cohort|trial|participants)", r"SomaLogic.{0,30}INTERVAL")),
    ("Fenland", "pQTL", (r"Fenland",)),
    ("ARIC", "pQTL;eQTL", (r"(?-i:\bARIC\b)", r"Atherosclerosis Risk in Communities")),
    ("AGES-Reykjavik", "pQTL", (r"AGES.?Reykjavik",)),
    ("SCALLOP", "pQTL", (r"(?-i:\bSCALLOP\b)",)),
    ("Olink Explore", "pQTL", (r"Olink Explore",)),
    ("Emilsson", "pQTL", (r"Emilsson",)),
    ("Genes & Health Seer pGWAS", "pQTL",
     (r"pGWAS_GandH_seer", r"Genes (?:&|and) Health.{0,50}Seer", r"Pietzner.{0,30}Seer")),
    # meQTL
    ("GoDMC", "meQTL", (r"GoDMC", r"Genetics of DNA Methylation Consortium")),
    ("ARIES/ALSPAC", "meQTL", (r"(?-i:\bARIES\b)", r"ALSPAC")),
    ("McRae/BSGS-LBC", "meQTL", (r"McRae", r"(?-i:\bBSGS\b)", r"Lothian Birth Cohort")),
    # caQTL and other molecular
    ("iPSCORE", "eQTL;caQTL", (r"iPSCORE",)),
    ("HipSci", "eQTL;pQTL", (r"HipSci", r"Human Induced Pluripotent Stem Cell Initiative")),
    ("Kumasaka caQTL", "caQTL", (r"Kumasaka",)),
    ("Degner dsQTL", "caQTL", (r"(?-i:\bdsQTL\b)", r"Degner")),
    ("BrainMeta", "eQTL;sQTL", (r"BrainMeta",)),
    ("Westra blood eQTL", "eQTL", (r"Westra",)),
    ("Zhernakova/BIOS", "eQTL", (r"Zhernakova",)),
    ("Võsa trans-eQTL", "eQTL", (r"Võsa", r"Vosa")),
    # catalogues that redistribute QTL statistics
    ("eQTL Catalogue", "eQTL;sQTL", (r"eQTL Catalogu?e",)),
    ("QTLbase", "eQTL;meQTL;pQTL", (r"QTLbase",)),
    ("PhenoScanner", "eQTL", (r"PhenoScanner",)),
    ("Open Targets Genetics", "eQTL", (r"Open Targets Genetics",)),
    ("IEU OpenGWAS", "eQTL;pQTL", (r"OpenGWAS", r"IEU GWAS database")),
    ("SMR data portal", "eQTL;sQTL;meQTL", (r"SMR (?:data )?portal",)),
    ("scQTLbase", "eQTL", (r"scQTLbase",)),
    ("mQTLdb", "meQTL", (r"mQTLdb",)),
)


# ── reading the paper ────────────────────────────────────────────────────────
#
# Europe PMC is the first stop, not the only one. It has no abstract for a large
# share of records and full text only for the PMC open-access subset, so a reader
# that stops there silently marks most of the literature "no data route found".
# Each source below answers a different failure: OpenAlex and Crossref carry
# abstracts Europe PMC lacks, Semantic Scholar and Unpaywall find an open PDF or
# landing page, and fetching that page reaches the Data Availability statement
# for papers no API indexes at all.

OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR = "https://api.semanticscholar.org/graph/v1/paper"
UNPAYWALL = "https://api.unpaywall.org/v2"
# Unpaywall and the OpenAlex polite pool both want a contact address, not a key.
POLITE_EMAIL = os.environ.get("LOCUSVIEW_CONTACT_EMAIL", "locusview@googlegroups.com")

DATA_SECTION_RE = re.compile(r"(data|code|material)[^<]{0,40}(availability|access|sharing)", re.I)
URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
INVERTED_LIMIT = 4000

REQUEST_PHRASES = (
    "available from the corresponding author", "available on request",
    "upon reasonable request", "upon request", "available from the authors",
)
CONTROLLED_PHRASES = (
    "dbgap", "ega-archive", "controlled access", "data access committee",
    "data access agreement", "material transfer agreement",
)

FILE_SUFFIXES = (
    ".tsv", ".txt", ".csv", ".gz", ".bgz", ".zip", ".bz2", ".parquet", ".vcf", ".bed",
    ".xlsx", ".rds", ".tar", ".h5", ".besd",
)
# Shared reference resources: real files, never a study's own QTL statistics.
REFERENCE_MARKERS = (
    ("ensembl", "Ensembl reference"),
    ("gencode", "GENCODE annotation"),
    ("blast/db", "BLAST database"),
    ("ftp.ncbi.nlm.nih.gov/genomes", "genome assembly"),
    ("refseq", "RefSeq reference"),
    ("hgdownload", "UCSC reference"),
    ("goldenpath", "UCSC reference"),
    ("alkesgroup/fusion/ldref", "LD reference panel"),
    ("1kg_phase", "1000 Genomes reference panel"),
    ("magma/aux_files", "MAGMA auxiliary files"),
    ("disgenet", "DisGeNET reference"),
    ("reftss", "refTSS reference"),
    ("ccres", "ENCODE cCRE registry"),
    ("roadmap/data", "Roadmap Epigenomics reference"),
    ("human-pangenomics", "pangenome assembly"),
    ("chain.gz", "liftOver chain file"),
    ("bulk-gex", "expression matrix, not QTL statistics"),
)
# Trait GWAS: association statistics, but not for a molecular phenotype.
GWAS_MARKERS = (
    ("finngen-public-data", "FinnGen GWAS release"),
    ("pan-ukb", "Pan-UKB GWAS release"),
    ("broad-ukb-sumstats", "UK Biobank GWAS release"),
    ("databases/gwas/summary_statistics", "GWAS Catalog release"),
)
RAW_MARKERS = ("/geo/", "gse", "/sra", "/ena/", "bioproject", "fastq")
# Code is never summary statistics, and a code repo is what a picker grabs when the real
# deposit is written as a bare accession rather than a link.
CODE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeocean", "/code")
# Software and documentation sites. A paper naming the tool it used is not naming its data,
# and these were being picked as download URLs: susieR, readthedocs, CRAN, Bioconductor.
SOFTWARE_HOSTS = (
    "readthedocs", "cran.r-project", "r-project.org", "bioconductor.org", "github.io",
    "pypi.org", "anaconda.org", "sourceforge", "software", "docs.", "/manual",
)

# Deposits are usually named, not linked. Each accession resolves to a real landing page.
ACCESSION_URLS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bS-BSST\d+\b"), "https://www.ebi.ac.uk/biostudies/studies/{0}", "supplement"),
    (re.compile(r"\bE-MTAB-\d+\b"),
     "https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{0}", "supplement"),
    (re.compile(r"\bEGA[SD]\d{6,}\b"),
     "https://ega-archive.org/datasets/{0}", "controlled"),
    (re.compile(r"\bphs\d{6}(?:\.v\d+\.p\d+)?\b"),
     "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id={0}", "controlled"),
)


# Data repositories mint DOIs, and a deposit is often written only as one. These resolve
# to the record, so a statement carrying nothing but a DOI still yields a usable route.
DATA_DOI_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b10\.5281/zenodo\.\d+\b", re.I), "supplement"),
    (re.compile(r"\b10\.6084/m9\.figshare\.\d+(?:\.v\d+)?\b", re.I), "supplement"),
    (re.compile(r"\b10\.5061/dryad\.[\w.]+\b", re.I), "supplement"),
    (re.compile(r"\b10\.17044/scilifelab\.\d+\b", re.I), "supplement"),
    (re.compile(r"\b10\.7303/syn\d+\b", re.I), "portal"),
)
SYNAPSE_RE = re.compile(r"\bsyn\d{6,}\b")
PRIDE_RE = re.compile(r"\bPXD\d{6,}\b")


def accession_urls(statement: str) -> list[tuple[str, str]]:
    """Deposit accessions and data DOIs in the text, as (url, access_route)."""
    found: list[tuple[str, str]] = []
    for pattern, template, route in ACCESSION_URLS:
        for accession in dict.fromkeys(pattern.findall(statement)):
            found.append((template.format(accession), route))
    for pattern, route in DATA_DOI_PATTERNS:
        for doi in dict.fromkeys(pattern.findall(statement)):
            found.append((f"https://doi.org/{doi}", route))
    for accession in dict.fromkeys(SYNAPSE_RE.findall(statement)):
        found.append((f"https://www.synapse.org/Synapse:{accession}", "portal"))
    for accession in dict.fromkeys(PRIDE_RE.findall(statement)):
        found.append((f"https://www.ebi.ac.uk/pride/archive/projects/{accession}", "supplement"))
    return found
# What makes a paper worth the slow sources: it names a QTL, or says something about data.
DEEP_READ_MARKERS = (
    "qtl", "quantitative trait loc", "summary statistic", "sumstat", "eqtl", "sqtl", "pqtl",
    "caqtl", "meqtl", "hqtl", "data availability", "publicly available", "are available",
    "deposited", "resource", "atlas", "we release",
)

QTL_MARKERS = (
    "qtl", "sumstat", "summary_stat", "summary-stat", "susie", "nominal", "molecular_trait",
    "cis_", "trans_", "besd",
)
CONTROLLED_HOSTS = ("dbgap", "projects/gap", "ega-archive", "ega.crg")
PORTAL_MARKERS = ("shiny", "browser", "portal", "/app/", "query", "search", "viewer")
REPOSITORY_LANDING = ("zenodo.org", "figshare.com", "datadryad.org", "osf.io", "synapse.org")


EPMC_REST = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def _get_text(url: str, *, timeout: int = 25) -> str:
    try:
        return _get(url, timeout=timeout).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return ""


def _json_or_none(url: str, *, timeout: int = 30) -> dict | None:
    try:
        return json.loads(_get(url, timeout=timeout).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _strip_tags(markup: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup)).strip()


def data_availability(markup: str) -> str:
    """The Data Availability section of an article, from XML or HTML."""
    chunks: list[str] = []
    for match in re.finditer(r"<sec[^>]*>(.*?)</sec>", markup, re.S):
        body = match.group(1)
        heading = re.search(r"<title[^>]*>(.*?)</title>", body, re.S)
        if heading and DATA_SECTION_RE.search(_strip_tags(heading.group(1))):
            chunks.append(_strip_tags(body))
    for tag in ("custom-meta", "notes", "ack", "back", "section", "div"):
        for match in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", markup, re.S):
            text = _strip_tags(match.group(1))
            if len(text) < 4000 and (
                DATA_SECTION_RE.search(text)
                or any(phrase in text.lower() for phrase in REQUEST_PHRASES)
            ):
                chunks.append(text)
    if not chunks:
        plain = _strip_tags(markup)
        chunks = [
            sentence
            for sentence in re.split(r"(?<=[.!?])\s+", plain)
            if "availab" in sentence.lower() or "deposit" in sentence.lower()
        ][:8]
    return " ".join(dict.fromkeys(chunks))[:6000]


def openalex_record(doi: str, pmid: str) -> dict | None:
    key = f"doi:{doi}" if doi else (f"pmid:{pmid}" if pmid else "")
    if not key:
        return None
    return _json_or_none(f"{OPENALEX}/{key}?mailto={POLITE_EMAIL}")


def openalex_abstract(record: dict) -> str:
    """OpenAlex ships abstracts as an inverted index; rebuild the text."""
    index = record.get("abstract_inverted_index") or {}
    if not index:
        return ""
    positions: list[tuple[int, str]] = [
        (position, word) for word, spots in index.items() for position in spots
    ]
    positions.sort()
    return " ".join(word for _, word in positions[:INVERTED_LIMIT])


def crossref_abstract(doi: str) -> str:
    if not doi:
        return ""
    record = _json_or_none(f"{CROSSREF}/{urllib.parse.quote(doi)}?mailto={POLITE_EMAIL}")
    message = (record or {}).get("message") or {}
    return _strip_tags(message.get("abstract", ""))


def semantic_scholar_record(doi: str, pmid: str) -> dict | None:
    key = f"DOI:{doi}" if doi else (f"PMID:{pmid}" if pmid else "")
    if not key:
        return None
    fields = "abstract,openAccessPdf,externalIds,title"
    return _json_or_none(f"{SEMANTIC_SCHOLAR}/{urllib.parse.quote(key)}?fields={fields}")


def unpaywall_locations(doi: str) -> list[str]:
    if not doi:
        return []
    record = _json_or_none(f"{UNPAYWALL}/{urllib.parse.quote(doi)}?email={POLITE_EMAIL}")
    if not record:
        return []
    found: list[str] = []
    for location in [record.get("best_oa_location")] + (record.get("oa_locations") or []):
        if not location:
            continue
        for field in ("url_for_pdf", "url_for_landing_page", "url"):
            value = location.get(field)
            if value:
                found.append(str(value))
    return list(dict.fromkeys(found))


def fetch_page(url: str, *, timeout: int = 12) -> str:
    """Fetch an article landing page. HTML only — a PDF tells us nothing without a parser."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if "html" not in response.headers.get("Content-Type", ""):
                return ""
            return response.read(2_000_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return ""


def classify_url(url: str, statement: str) -> tuple[str, str, str]:
    """(access_route, direct_download, reason) for one candidate URL."""
    low = url.casefold()
    host = urllib.parse.urlparse(low).netloc
    if host in PUBLICATION_HOSTS or any(h in low for h in ("frontiersin", "mdpi.com", "biorxiv")):
        return "unknown", "unknown", "URL is the article, not a data route"
    for marker, label in REFERENCE_MARKERS:
        if marker in low:
            return "unavailable", "no", f"URL is a {label}, not this study's QTL statistics"
    for marker, label in GWAS_MARKERS:
        if marker in low:
            return "unavailable", "no", f"URL is a {label}, not molecular QTL statistics"
    if any(marker in low for marker in CONTROLLED_HOSTS):
        return "controlled", "no", "controlled-access archive"
    if any(marker in low for marker in RAW_MARKERS):
        return "unavailable", "no", "URL points at raw data, not association statistics"
    if any(host in low for host in CODE_HOSTS):
        return "portal", "no", "URL is a code repository, not the data"
    if any(host in low for host in SOFTWARE_HOSTS):
        return "unknown", "unknown", "URL is software or documentation, not the data"
    looks_like_file = low.split("?")[0].endswith(FILE_SUFFIXES)
    names_qtl = any(marker in low for marker in QTL_MARKERS)
    if looks_like_file and names_qtl:
        return "direct", "yes", "file URL naming QTL statistics"
    if any(marker in low for marker in REPOSITORY_LANDING):
        return "supplement", "no", "repository record; the files sit inside it"
    if looks_like_file:
        return "direct", "yes", "downloadable file; confirm it is the statistics"
    if any(marker in host for marker in PORTAL_MARKERS):
        return "portal", "no", "query interface, not a bulk file"
    return "portal", "no", "landing page; no file named"


def choose_url(statement: str, urls: list[str]) -> tuple[str, str, str, str]:
    """Pick the most statistics-like URL. Returns (url, route, direct, reason).

    A deposit named only by accession beats every link in the statement: when a paper
    writes "deposited in BioStudies under S-BSST2922" and links only its GitHub, the
    links alone lead to the code.
    """
    deposits = accession_urls(statement)
    for url, route in deposits:
        if route == "supplement":
            return url, route, "no", "deposit accession named in the data statement"

    scored: list[tuple[int, str]] = []
    for candidate in urls:
        candidate = candidate.rstrip(".,;)]}")
        low = candidate.casefold()
        if urllib.parse.urlparse(low).netloc in PUBLICATION_HOSTS:
            continue
        score = 0
        if low.split("?")[0].endswith(FILE_SUFFIXES):
            score += 5
        if any(marker in low for marker in QTL_MARKERS):
            score += 5
        if any(marker in low for marker in REPOSITORY_LANDING):
            score += 2
        if any(marker in low for marker in RAW_MARKERS):
            score -= 4
        if any(marker in low for marker, _label in REFERENCE_MARKERS):
            score -= 6
        if any(host in low for host in CODE_HOSTS):
            score -= 8
        if any(host in low for host in SOFTWARE_HOSTS):
            score -= 8
        scored.append((score, candidate))
    if not scored and deposits:
        url, route = deposits[0]
        return url, route, "no", "only a controlled-access deposit accession was named"
    if not scored:
        low = statement.casefold()
        if any(phrase in low for phrase in REQUEST_PHRASES):
            return "", "request", "no", "statement says the data are available on request"
        if any(phrase in low for phrase in CONTROLLED_PHRASES):
            return "", "controlled", "no", "statement describes a controlled-access route"
        return "", "unknown", "unknown", "no data URL found in the sources read"
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    best = scored[0][1]
    route, direct, reason = classify_url(best, statement)
    return best, route, direct, reason


def epmc_records(pmids: list[str]) -> dict[str, dict]:
    """One Europe PMC call for a batch of PMIDs: pmcid, open-access flag, abstract."""
    wanted = [pmid for pmid in pmids if pmid]
    if not wanted:
        return {}
    args = {
        "query": " OR ".join(f"EXT_ID:{pmid}" for pmid in wanted),
        "format": "json",
        "pageSize": len(wanted),
        "resultType": "core",
    }
    data = _json_or_none(f"{EPMC}?{urllib.parse.urlencode(args)}", timeout=60)
    if data is None:
        return {}
    return {
        str(result.get("pmid")): result
        for result in (data.get("resultList") or {}).get("result", [])
    }


def read_paper(row: dict[str, str], core: dict) -> dict[str, str]:
    """Work through the sources until one yields a data statement, and say which did.

    Order matters: the cheapest and most structured source first, the slowest and
    least structured last. Every step records where its evidence came from, so a
    row read from a publisher page is never mistaken for one read from PMC.
    """
    doi = row.get("doi", "").strip()
    pmid = row.get("pmid", "").strip()
    title = row.get("publication_title", "")
    abstract = str(core.get("abstractText") or "")
    pmcid = str(core.get("pmcid") or "")
    open_access = str(core.get("isOpenAccess") or "N") == "Y"
    landing: list[str] = [
        str(item.get("url"))
        for item in ((core.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
        if item.get("url")
    ]

    # Fetching landing pages for every hit costs hours and buys nothing on a paper that
    # never mentions a QTL or a dataset. The cheap JSON sources run for everything; the
    # slow ones run for the papers that could actually carry data.
    signal = f"{title} {abstract}".casefold()
    deep = bool(row.get("qtl_type", "").strip()) or any(
        word in signal for word in DEEP_READ_MARKERS
    )

    statement, source = "", ""
    if pmcid and open_access:
        markup = _get_text(f"{EPMC_REST}/{pmcid}/fullTextXML", timeout=25)
        if markup:
            statement, source = data_availability(markup), "europepmc-fulltext"

    record = None
    if not statement or not abstract:
        record = openalex_record(doi, pmid)
        if record:
            abstract = abstract or openalex_abstract(record)
            for field in ("best_oa_location", "primary_location"):
                location = record.get(field) or {}
                for key in ("pdf_url", "landing_page_url"):
                    if location.get(key):
                        landing.append(str(location[key]))
            if not statement and abstract:
                statement, source = data_availability(abstract), "openalex-abstract"

    if not statement:
        crossref = crossref_abstract(doi)
        if crossref:
            abstract = abstract or crossref
            statement, source = data_availability(crossref), "crossref-abstract"

    if not statement and deep:
        scholar = semantic_scholar_record(doi, pmid) or {}
        if scholar.get("abstract"):
            abstract = abstract or str(scholar["abstract"])
            statement, source = data_availability(str(scholar["abstract"])), "semanticscholar"
        pdf = (scholar.get("openAccessPdf") or {}).get("url")
        if pdf:
            landing.append(str(pdf))

    if not statement and deep:
        landing.extend(unpaywall_locations(doi))
        # Last resort: resolve the DOI itself. Many publishers serve the Data Availability
        # section in the landing HTML even when no API carries it and no OA copy exists.
        if doi:
            landing.append(f"https://doi.org/{doi}")
        for url in list(dict.fromkeys(landing))[:3]:
            page = fetch_page(url)
            if not page:
                continue
            found = data_availability(page)
            if found:
                statement, source = found, "publisher-page"
                break

    if not statement and abstract:
        statement, source = abstract, "abstract-only"
    if not statement:
        source = "not-found"

    urls = URL_IN_TEXT_RE.findall(statement)
    url, route, direct, reason = choose_url(statement, urls)
    corpus = f"{title} {abstract} {statement}"
    named = datasets_in(corpus)
    values = {
        "qtl_type": row.get("qtl_type", "") or detect_qtl_types(corpus),
        # Which QTL dataset the paper used is the identity the verifier deduplicates on.
        "dataset_name": row.get("dataset_name", "") or ";".join(name for name, _ in named),
        "access_route": route,
        "direct_download": direct,
        "evidence_source": source,
        # Keep enough of the statement that `name-datasets` can re-match against it later:
        # at 400 characters the deposit sentence is routinely cut off, and a re-run then
        # erases a dataset name that the first read had found in the full text.
        "extraction_note": f"{source}: {reason}. {statement[:1500]}".strip(),
    }
    if url:
        values["download_url"] = url
    emails = sorted(set(EMAIL_RE.findall(f"{statement} {core.get('affiliation', '')}")))
    if emails and not row.get("contact_email", "").strip():
        values["contact_email"] = ";".join(emails[:3])
    return values


def detect_qtl_types(text: str) -> str:
    found = [label for label, pattern in QTL_TYPE_PATTERNS if pattern.search(text)]
    return ";".join(dict.fromkeys(found))


def read_table(
    table: Path, *, limit: int, workers: int, batch: int, reread: bool
) -> dict[str, int]:
    """Read every unread row and record what its sources said."""
    fields, rows = read_review_table(table)
    fields = fields + [c for c in REVIEW_COLUMNS if c not in fields]
    for row in rows:
        row.setdefault("evidence_source", "")
    pending = [
        row for row in rows
        if reread or not row.get("evidence_source", "").strip()
    ]
    if limit:
        pending = pending[:limit]
    counts: Counter[str] = Counter()
    by_id = {row["record_id"]: row for row in rows}
    done = 0
    for start in range(0, len(pending), batch):
        chunk = pending[start : start + batch]
        core = epmc_records([row.get("pmid", "") for row in chunk])
        def read_with_core(row: dict[str, str], records: dict[str, dict] = core) -> dict[str, str]:
            return read_paper(row, records.get(row.get("pmid", ""), {}))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(read_with_core, chunk))
        for row, values in zip(chunk, results, strict=True):
            target = by_id[row["record_id"]]
            for field, value in values.items():
                if value:
                    target[field] = value
            counts[values.get("evidence_source", "not-found")] += 1
        done += len(chunk)
        write_review_table(table, fields, rows)
        print(f"  {done}/{len(pending)} read", file=sys.stderr, flush=True)
        time.sleep(0.2)
    write_review_table(table, fields, rows)
    return dict(counts)


# Registry name → eQTL Catalogue study_label. Only pairs that the catalogue index itself
# confirms; `resolve` then supplies a URL it has checked with a HEAD request.
CATALOGUE_STUDIES: dict[str, str] = {
    "Alasoo macrophage": "Alasoo_2018",
    "BLUEPRINT": "BLUEPRINT",
    "BrainSeq": "BrainSeq",
    "Braineac/UKBEC": "Braineac2",
    "CEDAR": "CEDAR",
    "CommonMind": "CommonMind",
    "DICE": "Schmiedel_2018",
    "Fairfax monocyte": "Fairfax_2014",
    "GEUVADIS": "GEUVADIS",
    "GTEx": "GTEx",
    "HipSci": "HipSci",
    "INTERVAL/SomaLogic": "Sun_2018",
    "Kasela": "Kasela_2017",
    "Nedelec/Quach macrophage": "Nedelec_2016",
    "OneK1K": "OneK1K",
    "CLUES/Perez lupus": "Perez_2022",
    "ROSMAP": "ROSMAP",
    "Randolph influenza": "Randolph_2021",
    "TwinsUK/MuTHER": "TwinsUK",
    "iPSCORE": "iPSCORE",
}

DATASET_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (name, types, re.compile(r"(?:" + "|".join(aliases) + r")", re.I))
    for name, types, aliases in QTL_DATASET_REGISTRY
)

# "we generated/present the X cohort" — how a paper announces a dataset of its own.
NEW_DATASET_RE = re.compile(
    r"(?:we (?:present|report|generated|created|assembled|introduce)|here we (?:present|describe))"
    r"[^.]{0,80}?\b([A-Z][A-Za-z0-9]{2,}(?:[- ][A-Z0-9][A-Za-z0-9]{1,}){0,3})\b"
)


def datasets_in(text: str) -> list[tuple[str, str]]:
    """Every registered QTL dataset this text names, as (canonical name, QTL types)."""
    return [
        (name, types) for name, types, pattern in DATASET_PATTERNS if pattern.search(text)
    ]


def name_datasets(table: Path, *, overwrite: bool) -> Counter[str]:
    """Fill dataset_name from the registry, so the verifier's dedupe has an identity to key on."""
    fields, rows = read_review_table(table)
    fields = fields + [c for c in REVIEW_COLUMNS if c not in fields]
    counts: Counter[str] = Counter()
    for row in rows:
        if row.get("dataset_name", "").strip() and not overwrite:
            counts["already named"] += 1
            continue
        text = " ".join(
            (
                row.get("publication_title", ""),
                row.get("extraction_note", ""),
                row.get("download_url", ""),
            )
        )
        found = datasets_in(text)
        if not found:
            # On a re-run, a row that no longer matches must lose its old name —
            # leaving it would keep a correction from ever taking effect.
            if overwrite:
                row["dataset_name"] = ""
            counts["no registered dataset named"] += 1
            continue
        row["dataset_name"] = ";".join(name for name, _ in found)
        if not row.get("qtl_type", "").strip():
            types = [t for _, kinds in found for t in kinds.split(";")]
            row["qtl_type"] = ";".join(dict.fromkeys(types))
        for name, _ in found:
            counts[name] += 1
    write_review_table(table, fields, rows)
    return counts


def cmd_name_datasets(args: argparse.Namespace) -> int:
    counts = name_datasets(args.table, overwrite=args.overwrite)
    unnamed = counts.pop("no registered dataset named", 0)
    already = counts.pop("already named", 0)
    for name, count in counts.most_common():
        print(f"{count:6d}  {name}")
    print(f"\n{len(counts)} registered datasets named across the table")
    print(f"{unnamed} rows name no registered dataset; {already} already had a name")
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────


def cmd_search(args: argparse.Namespace) -> int:
    hits = search(
        args.query, args.release, quant=args.quant, min_n=args.min_n, limit=args.top
    )
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


def cmd_papers(args: argparse.Namespace) -> int:
    found = papers(args.query, limit=args.top)
    for paper in found:
        paper.matched_terms = ["ad-hoc"]
    if args.append:
        added = append_review(args.append, found, args.search_date)
        print(f"added {added} new rows to {args.append} ({len(found)} hits)", file=sys.stderr)
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
        print(f"  QTL types  : {', '.join(p.qtl_types) or 'other/unspecified QTL'}")
        if p.accessions:
            print(f"  accessions : {', '.join(p.accessions)}")
        if p.emails:
            print(f"  contact    : {', '.join(p.emails)}")
        for url in p.urls:
            print(f"  fulltext   : {url}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    families = tuple(args.families)
    unknown = [f for f in families if f not in REVIEW_TERM_FAMILIES]
    if unknown:
        print(
            f"unknown query families: {', '.join(unknown)}; "
            f"available: {', '.join(REVIEW_TERM_FAMILIES)}",
            file=sys.stderr,
        )
        return 1
    out = review_table_path(args.out, args.search_date)
    found = sweep(args.query, families, top_per_query=args.top_per_query)
    if args.append and out.exists():
        added = append_review(out, found, args.search_date)
        print(f"added {added} new rows from {len(found)} hits → {out}")
    else:
        written = write_review(out, found, args.search_date)
        print(f"wrote {written} deduplicated literature rows → {out}")
    print(
        "Rows are literature hits, not datasets: read each paper, then record what it says "
        "with `update`. download_url, qtl_context, population and sample_size stay blank "
        "until the full text supplies them.",
        file=sys.stderr,
    )
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    counts = read_table(
        args.table,
        limit=args.limit,
        workers=args.workers,
        batch=args.batch,
        reread=args.reread,
    )
    print(f"evidence sources: {counts}")
    unread = counts.get("not-found", 0)
    if unread:
        print(
            f"{unread} papers yielded nothing from any source — search for them by title, "
            "or record why the data route cannot be established",
            file=sys.stderr,
        )
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    try:
        row = update_record(args.table, args.record_id, args.set)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    title = textwrap.shorten(row["publication_title"], 60, placeholder="…")
    print(f"record {row['record_id']}: {title}")
    for field in UPDATABLE:
        if row.get(field):
            print(f"  {field:<17} {row[field]}")
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
    today = date.today().isoformat()

    def add_release(p: argparse.ArgumentParser) -> None:
        p.add_argument("--release", default="r7", choices=["r7", "r8", "r8_beta"])

    s = sub.add_parser(
        "review", help="keyword sweep of Europe PMC → qtlliteraturereview-<date>.tsv"
    )
    s.add_argument(
        "query",
        nargs="?",
        default=HUMAN_SCOPE,
        help='organism or narrower scope, e.g. "human AND brain" (default: human studies)',
    )
    s.add_argument(
        "--families",
        nargs="+",
        default=["all"],
        metavar="FAMILY",
        help=(
            "query families to run: "
            + ", ".join(REVIEW_TERM_FAMILIES)
            + " (default: all)"
        ),
    )
    s.add_argument("--top-per-query", type=int, default=100)
    s.add_argument(
        "--out",
        type=Path,
        help="output table (default: qtlliteraturereview-<search date>.tsv)",
    )
    s.add_argument("--search-date", default=today, help="ISO date recorded in every row")
    s.add_argument("--append", action="store_true", help="add new rows to an existing table")
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("papers", help="one ad-hoc Europe PMC query")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--json", action="store_true")
    s.add_argument("--append", type=Path, help="append new hits to this review table")
    s.add_argument("--search-date", default=today)
    s.set_defaults(func=cmd_papers)

    s = sub.add_parser("read", help="read every unread row through all sources, in bulk")
    s.add_argument("table", type=Path, help="the review table to fill in place")
    s.add_argument("--limit", type=int, default=0, help="read at most N rows this run")
    s.add_argument("--workers", type=int, default=8)
    s.add_argument("--batch", type=int, default=100, help="rows per metadata call and table write")
    s.add_argument(
        "--reread", action="store_true", help="re-read rows that already have an evidence_source"
    )
    s.set_defaults(func=cmd_read)

    s = sub.add_parser(
        "name-datasets", help="fill dataset_name from the registry of known QTL resources"
    )
    s.add_argument("table", type=Path)
    s.add_argument("--overwrite", action="store_true", help="replace names already recorded")
    s.set_defaults(func=cmd_name_datasets)

    s = sub.add_parser("update", help="record what reading one paper established")
    s.add_argument("table", type=Path, help="the review table to edit in place")
    s.add_argument("record_id", help="record_id of the row to update")
    s.add_argument(
        "--set",
        action="append",
        required=True,
        metavar="FIELD=VALUE",
        help="one assignment per flag; fields: " + ", ".join(UPDATABLE),
    )
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("search", help="fuzzy-search the eQTL Catalogue index")
    s.add_argument("query", help='tissue, cell type or condition, e.g. "pancreatic islet"')
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--quant", help="ge, exon, tx, txrev, leafcutter, aptamer, microarray")
    s.add_argument("--min-n", type=int, default=0, help="minimum sample size")
    s.add_argument("--json", action="store_true")
    add_release(s)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("resolve", help="catalogue dataset id → verified download URLs")
    s.add_argument("dataset_id", help="e.g. QTD000001")
    s.add_argument("--json", action="store_true")
    s.add_argument(
        "--save-metadata",
        type=Path,
        help="upsert this dataset into a shared metadata store (JSONL) for sumstats-manifest",
    )
    add_release(s)
    s.set_defaults(func=cmd_resolve)

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
