#!/usr/bin/env python3
"""Find the largest-sample GWAS Catalog study for a trait, with download links.

Given a free-text trait name, this:
  1. resolves the name to candidate EFO terms (fuzzy, via the Solr search API);
  2. pulls every study mapped to those terms, plus exact reported-trait matches;
  3. ranks them by discovery sample size;
  4. resolves FTP paths for the winner's summary statistics and metadata YAML.

Standard library only, so it runs without touching the project's dependencies.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

REST = "https://www.ebi.ac.uk/gwas/rest/api"
SOLR = "https://www.ebi.ac.uk/gwas/api/search"
FTP = "https://ftp.ebi.ac.uk/pub/databases/gwas/summary_statistics"
UA = "locusview-gwas-catalog-lookup/1.0 (https://github.com/boxiangliulab/locusview)"

HREF_RE = re.compile(r'href="([^"?][^"]*)"')


class LookupError_(RuntimeError):
    """Raised when the catalog cannot answer the question."""


def _get(url: str, *, tries: int = 3, timeout: int = 60) -> bytes:
    """GET with a couple of retries — the EBI endpoints rate-limit under bursts."""
    last: Exception | None = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return bytes(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
        if attempt < tries - 1:
            import time

            time.sleep(2 * (attempt + 1))
    raise LookupError_(f"GET failed after {tries} tries: {url} ({last})")


def _get_json(url: str) -> dict:
    return json.loads(_get(url).decode("utf-8"))


# ── step 1: trait name → EFO terms ────────────────────────────────────────────


@dataclass
class EfoTerm:
    label: str
    short_form: str
    uri: str
    study_count: int


# Only structural stopwords belong here. Words like "volume", "concentration"
# and "percentage" look generic but are exactly what separates MCV from MCH from
# MCHC, so treating them as noise collapses three distinct traits into one.
GENERIC = frozenset({"of", "the", "in", "and", "or", "a", "an", "to", "for"})


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def is_relevant(
    query: str, label: str, synonyms: list[str] | None = None, *, cutoff: float = 0.85
) -> bool:
    """Keep a term only if it is about the same thing as the query.

    Solr scores lexically, so a query like "basophil count" also returns
    "nevus count" and the broad parent "myeloid leukocyte count" — and because
    parents carry hundreds of studies, letting them through hands back the
    largest study of a *different* trait. A term is kept when every distinctive
    (non-generic) query token has a near-match among the label's tokens.

    Matching is per-token on purpose. Whole-string similarity puts
    "basophil count" vs "eosinophil count" at 0.80 — high enough to leak a
    sibling blood-cell trait — while the token pair basophil/eosinophil scores
    0.67 and is correctly rejected. Token matching still absorbs plurals and
    typos (basophil/basophils = 0.94).
    """
    distinctive = _tokens(query) - GENERIC
    # EFO labels are canonical ("leukocyte count"); the query may use the common
    # name ("white blood cell count"), which only appears among the synonyms.
    for candidate in [label, *(synonyms or [])]:
        cand = _tokens(candidate)
        if not distinctive:
            ratio = difflib.SequenceMatcher(None, query.lower(), candidate.lower()).ratio()
            if ratio >= cutoff:
                return True
            continue
        if all(
            any(
                token == other or difflib.SequenceMatcher(None, token, other).ratio() >= cutoff
                for other in cand
            )
            for token in distinctive
        ):
            return True
    return False


def find_efo_terms(
    query: str, limit: int = 8, *, loose: bool = False
) -> tuple[list[EfoTerm], list[str], list[EfoTerm]]:
    """Discover EFO terms and author-reported trait strings similar to the query.

    Returns (kept_terms, kept_reported_traits, dropped_terms).

    Two vocabularies matter and they do not agree: EFO gives canonical labels
    ("leukocyte count") while studies declare free-text reported traits
    ("White blood cell count", "Basophill count (UKB data field 30160)").
    Solr's trait documents carry both, so one query harvests each. Relevance is
    then judged per *string* rather than per term — a term's reported-trait list
    can contain both on-target and off-target names.
    """
    args = {"q": query, "max": max(limit * 6, 40), "fq": "resourcename:trait"}
    docs = _get_json(f"{SOLR}?{urllib.parse.urlencode(args)}")["response"]["docs"]

    kept: list[EfoTerm] = []
    dropped: list[EfoTerm] = []
    reported: set[str] = set()
    for doc in docs:
        short = doc.get("shortForm") or []
        label = doc.get("title") or ""
        if not short or not label:
            continue
        term = EfoTerm(
            label=label,
            short_form=short[0],
            uri=(doc.get("mappedUri") or f"http://www.ebi.ac.uk/efo/{short[0]}"),
            study_count=int(doc.get("studyCount") or 0),
        )
        synonyms = [str(x) for x in (doc.get("synonyms") or [])]
        if loose or is_relevant(query, label) or any(is_relevant(query, syn) for syn in synonyms):
            kept.append(term)
        else:
            dropped.append(term)

        # Reported-trait strings are judged individually, so an off-target term
        # can still contribute the one author label that does match.
        for name in doc.get("reportedTrait") or []:
            if loose or is_relevant(query, str(name)):
                reported.add(str(name))

    if is_relevant(query, query):  # the query itself is always worth trying verbatim
        reported.add(query)
    return kept[:limit], sorted(reported), dropped


# ── step 2: EFO terms → studies ───────────────────────────────────────────────


@dataclass
class Study:
    accession: str
    reported_trait: str
    efo_label: str
    n_initial: int
    sample_description: str
    ancestries: list[str]
    has_sumstats: bool
    pubmed_id: str = ""
    first_author: str = ""
    publication_date: str = ""
    matched_via: str = ""

    @property
    def api_url(self) -> str:
        return f"{REST}/studies/{self.accession}"

    @property
    def catalog_url(self) -> str:
        return f"https://www.ebi.ac.uk/gwas/studies/{self.accession}"


def _n_initial(raw: dict) -> int:
    """Discovery sample size: the sum over 'initial' ancestry rows.

    Replication rows are deliberately excluded — two studies are only comparable
    on the sample that produced the association statistics.
    """
    total = 0
    for anc in raw.get("ancestries") or []:
        if anc.get("type") == "initial":
            total += int(anc.get("numberOfIndividuals") or 0)
    return total


def _ancestry_labels(raw: dict) -> list[str]:
    out: list[str] = []
    for anc in raw.get("ancestries") or []:
        if anc.get("type") != "initial":
            continue
        out.extend(g.get("ancestralGroup", "") for g in anc.get("ancestralGroups") or [])
    return sorted({a for a in out if a})


def _to_study(raw: dict, efo_label: str, matched_via: str) -> Study:
    pub = raw.get("publicationInfo") or {}
    return Study(
        accession=raw.get("accessionId", ""),
        reported_trait=(raw.get("diseaseTrait") or {}).get("trait", ""),
        efo_label=efo_label,
        n_initial=_n_initial(raw),
        sample_description=raw.get("initialSampleSize") or "",
        ancestries=_ancestry_labels(raw),
        has_sumstats=bool(raw.get("fullPvalueSet")),
        pubmed_id=str(pub.get("pubmedId") or ""),
        first_author=(pub.get("author") or {}).get("fullname", ""),
        publication_date=pub.get("publicationDate") or "",
        matched_via=matched_via,
    )


def _paged_studies(url: str, efo_label: str, matched_via: str, page_size: int = 200) -> list[Study]:
    studies: list[Study] = []
    page = 0
    while True:
        sep = "&" if "?" in url else "?"
        data = _get_json(f"{url}{sep}size={page_size}&page={page}")
        batch = (data.get("_embedded") or {}).get("studies") or []
        studies.extend(_to_study(raw, efo_label, matched_via) for raw in batch)
        info = data.get("page") or {}
        page += 1
        if page >= int(info.get("totalPages") or 1):
            break
    return studies


def studies_for_term(term: EfoTerm) -> list[Study]:
    url = f"{REST}/studies/search/findByEfoUri?uri={urllib.parse.quote(term.uri, safe='')}"
    return _paged_studies(url, term.label, f"EFO {term.short_form}")


def studies_for_reported_trait(trait: str) -> list[Study]:
    """Reported traits are author strings and often differ from the EFO label."""
    url = f"{REST}/studies/search/findByDiseaseTrait?diseaseTrait={urllib.parse.quote(trait)}"
    try:
        return _paged_studies(url, "", "reported trait")
    except (LookupError_, urllib.error.HTTPError):
        return []


# ── metadata record for the shared store ─────────────────────────────────────

# GWAS Catalog ancestral groups → the population codes the manifests use.
POPULATION = {
    "European": "EUR",
    "African American or Afro-Caribbean": "AFR",
    "African unspecified": "AFR",
    "Sub-Saharan African": "AFR",
    "African": "AFR",
    "East Asian": "EAS",
    "South Asian": "SAS",
    "South East Asian": "SAS",
    "Hispanic or Latin American": "AMR",
    "Native American": "AMR",
}


def population_code(ancestries: list[str]) -> str:
    """One code, or ALL when the discovery sample spans more than one group."""
    codes = {POPULATION.get(a, "") for a in ancestries}
    codes.discard("")
    if len(codes) == 1:
        return codes.pop()
    return "ALL"


def metadata_record(study: Study, files: Files) -> dict:
    """The fields sumstats-manifest needs but cannot read out of a data file."""
    return {
        "kind": "gwas",
        "key": study.accession,
        "accession": study.accession,
        "trait": re.sub(r"[^A-Za-z0-9]+", "_", study.reported_trait).strip("_"),
        "datasource": "GWAS Catalog",
        "population": population_code(study.ancestries),
        # Everything the catalog carries here is a quantitative or case/control
        # measure; it cannot be told apart from the API, so default and let the
        # caller correct it.
        "type": "quant",
        "sample_size": study.n_initial,
        "url": study.catalog_url,
        "download_url": (files.harmonised or files.raw or [""])[0],
        "provenance": {
            "source": "GWAS Catalog REST API",
            "fetched": date.today().isoformat(),
            "sample_size_from": "sum of initial-ancestry numberOfIndividuals",
            "reported_trait": study.reported_trait,
            "ancestries": study.ancestries,
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


# ── step 3: accession → FTP paths ─────────────────────────────────────────────


@dataclass
class Files:
    dir_url: str = ""
    raw: list[str] = field(default_factory=list)
    meta_yaml: list[str] = field(default_factory=list)
    harmonised: list[str] = field(default_factory=list)
    harmonised_meta: list[str] = field(default_factory=list)
    md5: list[str] = field(default_factory=list)
    note: str = ""


def bucket(accession: str) -> str:
    """FTP studies are binned in blocks of 1000, e.g. GCST90002001-GCST90003000."""
    num = int(accession.removeprefix("GCST"))
    lo = ((num - 1) // 1000) * 1000 + 1
    return f"GCST{lo:06d}-GCST{lo + 999:06d}"


def _listing(url: str) -> list[str]:
    try:
        html = _get(url, tries=2).decode("utf-8", "replace")
    except urllib.error.HTTPError:
        return []
    return [h for h in HREF_RE.findall(html) if not h.startswith("/")]


def resolve_files(accession: str) -> Files:
    """List the study's FTP directory.

    Filenames are NOT constructible: harmonised files appear both as
    '{accession}.h.tsv.gz' and as the older '{pmid}-{accession}-{efo}.h.tsv.gz',
    and the raw file carries a build suffix. Always list, never guess.
    """
    base = f"{FTP}/{bucket(accession)}/{accession}"
    entries = _listing(f"{base}/")
    if not entries:
        return Files(note="no summary-statistics directory on the FTP site")

    files = Files(dir_url=f"{base}/")
    for name in entries:
        if name.endswith("/"):
            continue
        url = f"{base}/{name}"
        if name.endswith("-meta.yaml"):
            files.meta_yaml.append(url)
        elif name.startswith("md5sum"):
            files.md5.append(url)
        elif name.endswith((".tsv", ".tsv.gz")):
            files.raw.append(url)

    if any(e.rstrip("/") == "harmonised" for e in entries):
        for name in _listing(f"{base}/harmonised/"):
            url = f"{base}/harmonised/{name}"
            if name.endswith("-meta.yaml"):
                files.harmonised_meta.append(url)
            elif name.endswith(".h.tsv.gz"):
                files.harmonised.append(url)
    return files


# ── orchestration ─────────────────────────────────────────────────────────────


def collect(
    query: str, *, max_terms: int, require_sumstats: bool, loose: bool = False
) -> tuple[list[EfoTerm], list[str], list[EfoTerm], list[Study]]:
    terms, reported, dropped = find_efo_terms(query, max_terms, loose=loose)
    if not terms and not reported:
        hint = " (candidates failed the relevance filter; retry with --loose)" if dropped else ""
        raise LookupError_(f"nothing in the catalog matched {query!r}{hint}")

    by_accession: dict[str, Study] = {}
    # Exact reported-trait lookups first: findByDiseaseTrait is an exact,
    # case-insensitive match, so whatever it returns is certain to be on target.
    for name in reported:
        for study in studies_for_reported_trait(name):
            by_accession.setdefault(study.accession, study)
    for term in terms:
        for study in studies_for_term(term):
            by_accession.setdefault(study.accession, study)

    studies = list(by_accession.values())
    if require_sumstats:
        studies = [s for s in studies if s.has_sumstats]
    studies.sort(key=lambda s: s.n_initial, reverse=True)
    return terms, reported, dropped, studies


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("trait", help='trait name, e.g. "basophil count"')
    ap.add_argument("--top", type=int, default=10, help="candidates to show (default 10)")
    ap.add_argument("--max-terms", type=int, default=8, help="EFO terms to expand (default 8)")
    ap.add_argument("--ancestry", help="keep only studies whose discovery ancestry contains this")
    ap.add_argument("--any-sumstats", action="store_true", help="do not require summary statistics")
    ap.add_argument(
        "--loose", action="store_true", help="skip the relevance filter on matched EFO terms"
    )
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    ap.add_argument("--save-yaml", type=Path, help="download the winner's metadata YAML here")
    ap.add_argument(
        "--save-metadata",
        type=Path,
        help="upsert the winner into a shared metadata store (JSONL) for sumstats-manifest",
    )
    args = ap.parse_args()

    terms, reported, dropped, studies = collect(
        args.trait,
        max_terms=args.max_terms,
        require_sumstats=not args.any_sumstats,
        loose=args.loose,
    )
    if args.ancestry:
        want = args.ancestry.lower()
        studies = [s for s in studies if any(want in a.lower() for a in s.ancestries)]
    if not studies:
        print(f"no study matched {args.trait!r} with the current filters", file=sys.stderr)
        return 1

    winner = studies[0]
    files = resolve_files(winner.accession)

    if args.json:
        print(
            json.dumps(
                {
                    "query": args.trait,
                    "efo_terms": [asdict(t) for t in terms],
                    "reported_traits_matched": reported,
                    "efo_terms_dropped": [asdict(t) for t in dropped],
                    "winner": asdict(winner) | {"files": asdict(files)},
                    "candidates": [asdict(s) for s in studies[: args.top]],
                },
                indent=2,
            )
        )
    else:
        print(f"query: {args.trait!r}")
        print("EFO terms expanded:")
        for t in terms:
            print(f"  {t.short_form:<16} {t.label}  ({t.study_count} studies)")
        print("reported trait names matched:")
        for name in reported:
            print(f"  {name}")
        if dropped:
            print("dropped as off-target (use --loose to keep):")
            for t in dropped:
                print(f"  {t.short_form:<16} {t.label}  ({t.study_count} studies)")
        print(f"\ncandidates ({len(studies)} after filters), largest discovery N first:")
        print(f"  {'accession':<15} {'N':>10}  {'sumstats':<8} {'ancestry':<22} trait")
        for s in studies[: args.top]:
            anc = ",".join(s.ancestries)[:22]
            flag = "yes" if s.has_sumstats else "no"
            print(f"  {s.accession:<15} {s.n_initial:>10,}  {flag:<8} {anc:<22} {s.reported_trait}")

        print(f"\nlargest: {winner.accession} — {winner.reported_trait}")
        print(f"  sample     : {winner.sample_description}")
        if winner.first_author:
            print(
                f"  publication: {winner.first_author} {winner.publication_date} "
                f"PMID {winner.pubmed_id}"
            )
        print(f"  catalog    : {winner.catalog_url}")
        print(f"  api        : {winner.api_url}")
        if files.note:
            print(f"  files      : {files.note}")
        for label, urls in (
            ("harmonised", files.harmonised),
            ("harm. meta", files.harmonised_meta),
            ("raw", files.raw),
            ("meta yaml", files.meta_yaml),
            ("md5", files.md5),
        ):
            for url in urls:
                print(f"  {label:<11}: {url}")

    if args.save_metadata:
        record = metadata_record(winner, files)
        action = save_metadata(args.save_metadata, record)
        print(
            f"\nmetadata {action} in {args.save_metadata}: "
            f"{record['accession']} · {record['trait']} · {record['population']} · "
            f"N={record['sample_size']}",
            file=sys.stderr,
        )

    if args.save_yaml:
        targets = files.harmonised_meta or files.meta_yaml
        if not targets:
            print("no metadata YAML to save", file=sys.stderr)
            return 1
        args.save_yaml.mkdir(parents=True, exist_ok=True)
        for url in targets:
            dest = args.save_yaml / url.rsplit("/", 1)[-1]
            dest.write_bytes(_get(url))
            print(f"saved {dest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
