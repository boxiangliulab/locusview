#!/usr/bin/env python3
"""Inspect downloaded GWAS/QTL summary statistics and record them in a manifest.

  inspect     peek at a file, propose a column mapping, show sample rows
  fill-table  read the first lines of every downloaded file and fill the review table
  add-gwas    append or update a row in gwas_manifest.tsv
  add-qtl     append or update a row in qtl_manifest.tsv
  validate    re-check every row of a manifest against the files on disk

Stage 4 of the QTL pipeline is `fill-table`: it reads the head of each file that
download_qtl fetched and writes the layout back into the review table, so the table
says what each file actually contains. `add-qtl` then promotes those rows into
qtl_manifest.tsv with their provenance.

Column mapping is inferred from the header; everything a file cannot tell you
about itself (accession, trait, population, sample size, URL) must be passed in.
Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

GWAS_COLUMNS = [
    "accession", "trait", "datasource", "population", "type", "sample_size",
    "file_path", "delimiter", "chrom_col", "position_col", "ref_col", "alt_col",
    "beta_col", "se_col", "pval_col", "rsid_col", "maf_col", "variant_id_col", "url",
]

QTL_COLUMNS = [
    "dataset", "qtl_type", "biocontext", "level_1_context", "level_2_context",
    "population", "sample_size", "file_path", "delimiter", "chrom_col", "position_col",
    "ref_col", "alt_col", "beta_col", "se_col", "pval_col", "rsid_col", "maf_col",
    "variant_id_col", "phenotype_id_col", "gene_id_mode", "url",
]

# Rows are keyed on these so re-running updates in place instead of duplicating.
GWAS_KEY = ("accession",)
QTL_KEY = ("dataset", "qtl_type", "biocontext")

# Header synonyms per slot, most specific first. Drawn from the formats actually
# in use: GWAS Catalog harmonised + pre-harmonised, GTEx v8/v10, eQTL Catalogue,
# tensorQTL, fastQTL, METAL, SAIGE, REGENIE, BOLT-LMM.
SYNONYMS: dict[str, list[str]] = {
    "chrom_col": ["chromosome", "chrom", "chr", "#chrom", "hm_chrom", "chr_name", "chrnum"],
    "position_col": [
        "position", "pos", "bp", "base_pair_location", "hm_pos", "chrom_start",
        "chr_position", "genpos", "start",
    ],
    # ref = non-effect allele, alt = effect allele (beta is w.r.t. alt).
    "ref_col": [
        "other_allele", "ref", "non_effect_allele", "allele0", "a2", "hm_other_allele",
        "reference_allele", "noneffect_allele",
    ],
    "alt_col": [
        "effect_allele", "alt", "allele1", "a1", "hm_effect_allele", "tested_allele",
        "coded_allele", "minor_allele",
    ],
    "beta_col": ["beta", "slope", "effect_size", "effect", "b", "hm_beta", "log_odds"],
    "se_col": ["standard_error", "slope_se", "se", "stderr", "sebeta", "beta_se", "log_odds_se"],
    "pval_col": [
        "p_value", "pval_nominal", "pvalue", "pval", "p", "p_bolt_lmm", "p.value",
        "p_value_association", "frequentist_add_pvalue",
    ],
    "rsid_col": [
        "rs_id_dbsnp155_grch38p13", "rsid", "rs_id", "snp", "snpid", "rs", "variant_rsid",
        "rs_id_dbsnp151_grch38p7", "hm_rsid",
    ],
    "maf_col": [
        "maf", "minor_allele_frequency", "effect_allele_frequency", "af", "freq",
        "a1freq", "eaf", "hm_effect_allele_frequency",
    ],
    "variant_id_col": ["variant_id", "variant", "varid", "snp_id", "id", "hm_variant_id"],
    "phenotype_id_col": [
        "phenotype_id", "molecular_trait_id", "gene_id", "gene", "peak_region",
        "phenotype", "pid", "feature_id",
    ],
}

# Slots without which a file is not usable downstream.
REQUIRED = ["chrom_col", "position_col", "ref_col", "alt_col", "beta_col", "pval_col"]


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


# ── reading files ─────────────────────────────────────────────────────────────


def expand(file_path: str) -> Path:
    """Resolve a path that may be a glob, e.g. '…cis_qtl_pairs.chr*.tsv.gz'.

    Sharded datasets are recorded in the manifest as one globbed row; only the
    first shard is read, since every shard shares a header.
    """
    if any(ch in file_path for ch in "*?["):
        matches = sorted(glob.glob(file_path))
        if not matches:
            raise FileNotFoundError(f"glob matched nothing: {file_path}")
        return Path(matches[0])
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)
    return path


def head_lines(path: Path, n: int) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:  # type: ignore[operator]
        out = []
        for _, line in zip(range(n), fh, strict=False):
            out.append(line.rstrip("\n"))
        return out


def sniff_delimiter(header: str) -> str:
    counts = {"\t": header.count("\t"), ",": header.count(","), " ": header.count(" ")}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] else "\t"


def escape_delim(delim: str) -> str:
    """The manifest stores a literal backslash-t, not a tab character."""
    return {"\t": "\\t", ",": ",", " ": " ", ";": ";"}.get(delim, delim)


# ── column mapping ────────────────────────────────────────────────────────────


@dataclass
class Inspection:
    path: Path
    file_path: str
    delimiter: str
    header: list[str]
    rows: list[list[str]]
    mapping: dict[str, str]
    unmapped_header: list[str]
    missing_required: list[str]
    notes: list[str]

    def sample(self, slot: str) -> str:
        col = self.mapping.get(slot)
        if not col or not self.rows:
            return ""
        try:
            return self.rows[0][self.header.index(col)]
        except (ValueError, IndexError):
            return ""


def map_columns(header: list[str]) -> tuple[dict[str, str], list[str]]:
    by_norm = {norm(h): h for h in header}
    mapping: dict[str, str] = {}
    for slot, candidates in SYNONYMS.items():
        for candidate in candidates:
            if candidate in by_norm:
                mapping[slot] = by_norm[candidate]
                break
    used = set(mapping.values())
    return mapping, [h for h in header if h not in used]


def infer_gene_id_mode(phenotype_value: str) -> str:
    """How to get a gene id out of phenotype_id, from the value's own shape.

    eQTL rows carry the gene directly ('ENSG00000261456.6' -> self); sQTL rows
    carry an intron cluster whose last colon-separated field is the gene
    ('chr6:32518666:32519370:clu_46120_-:ENSG00000198502.6'); caQTL rows carry a
    peak with no gene at all, and the column is left blank.
    """
    value = (phenotype_value or "").strip()
    if not value:
        return ""
    if re.fullmatch(r"ENSG\d+(\.\d+)?", value):
        return "self"
    if ":" in value and re.fullmatch(r"ENSG\d+(\.\d+)?", value.rsplit(":", 1)[-1]):
        return "phenotype_last_segment"
    return ""


def inspect(file_path: str, *, rows: int = 3) -> Inspection:
    path = expand(file_path)
    lines = head_lines(path, rows + 1)
    if not lines:
        raise ValueError(f"{path} is empty")

    delimiter = sniff_delimiter(lines[0])
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    table = list(reader)
    header, data = table[0], table[1:]

    mapping, unmapped = map_columns(header)
    missing = [slot for slot in REQUIRED if slot not in mapping]

    notes: list[str] = []
    if str(path) != file_path:
        notes.append(f"glob resolved to {path.name}; the manifest keeps the pattern")
    chrom = mapping.get("chrom_col")
    if chrom and data:
        value = data[0][header.index(chrom)]
        if not value.startswith("chr"):
            notes.append(f"{chrom} values are unprefixed ({value!r}), not 'chr{value}'")
    if "se_col" not in mapping:
        notes.append("no standard-error column — colocalisation needs one")
    if "rsid_col" not in mapping:
        notes.append("no rsID column — variants will need mapping by position")
    return Inspection(
        path=path,
        file_path=file_path,
        delimiter=delimiter,
        header=header,
        rows=data,
        mapping=mapping,
        unmapped_header=unmapped,
        missing_required=missing,
        notes=notes,
    )


# ── the shared metadata store ─────────────────────────────────────────────────
#
# Written by the gwas-catalog-lookup and qtl-data-finder skills:
#   find_gwas.py "basophil count" --save-metadata sumstats_metadata.jsonl
#   find_qtl.py resolve QTD000574 --save-metadata sumstats_metadata.jsonl
#
# It carries what a data file cannot state about itself — accession, trait,
# sample size, population, URL — so those are never typed twice or guessed here.

GWAS_FROM_STORE = ["accession", "trait", "datasource", "population", "type", "sample_size", "url"]
QTL_FROM_STORE = [
    "dataset", "qtl_type", "biocontext", "level_1_context", "level_2_context",
    "population", "sample_size", "url",
]


def load_store(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist — run gwas-catalog-lookup or qtl-data-finder "
            f"with --save-metadata first"
        )
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def find_record(store: list[dict], kind: str, key: str) -> dict:
    """Exact key first, then a unique case-insensitive match on the identifiers."""
    candidates = [r for r in store if r.get("kind") == kind]
    for record in candidates:
        if record.get("key") == key:
            return record
    needle = key.lower()
    loose = [
        r
        for r in candidates
        if needle in (r.get("key", "") or "").lower()
        or needle == (r.get("accession", "") or "").lower()
        or needle == (r.get("biocontext", "") or "").lower()
    ]
    if len(loose) == 1:
        return loose[0]
    if not loose:
        keys = ", ".join(sorted(r.get("key", "") for r in candidates)[:8]) or "(store is empty)"
        raise KeyError(f"no {kind} record for {key!r}. Known keys: {keys}")
    raise KeyError(
        f"{key!r} matches {len(loose)} {kind} records "
        f"({', '.join(r.get('key', '') for r in loose[:5])}) — pass the full key"
    )


def from_store(record: dict, fields: list[str]) -> dict[str, str]:
    out = {f: str(record.get(f, "") or "") for f in fields}
    blank = [f for f in fields if not out[f] and f != "level_2_context"]
    if blank:
        print(f"  store has no value for: {', '.join(blank)}", file=sys.stderr)
    return out


# ── manifest I/O ──────────────────────────────────────────────────────────────


def read_manifest(path: Path, columns: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames and [f.strip() for f in reader.fieldnames] != columns:
            raise ValueError(
                f"{path} has unexpected columns.\n  found:    {reader.fieldnames}\n"
                f"  expected: {columns}"
            )
        return [{k: (v or "") for k, v in row.items() if k} for row in reader]


def write_manifest(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    tmp.replace(path)


def upsert(
    path: Path, columns: list[str], key: tuple[str, ...], row: dict[str, str]
) -> str:
    rows = read_manifest(path, columns)
    ident = tuple(row.get(k, "") for k in key)
    for i, existing in enumerate(rows):
        if tuple(existing.get(k, "") for k in key) == ident:
            rows[i] = row
            write_manifest(path, columns, rows)
            return "updated"
    rows.append(row)
    write_manifest(path, columns, rows)
    return "added"


# ── commands ──────────────────────────────────────────────────────────────────


def _print_inspection(found: Inspection) -> None:
    print(f"file      : {found.path}")
    print(f"delimiter : {escape_delim(found.delimiter)}  ({len(found.header)} columns)")
    print("mapping   :")
    for slot in [*REQUIRED, "se_col", "rsid_col", "maf_col", "variant_id_col", "phenotype_id_col"]:
        col = found.mapping.get(slot, "")
        mark = " " if col else "!"
        print(f"  {mark} {slot:<18} {col:<32} {found.sample(slot)[:34]}")
    if found.unmapped_header:
        print(f"unmapped  : {', '.join(found.unmapped_header)}")
    for note in found.notes:
        print(f"note      : {note}")
    if found.missing_required:
        print(f"MISSING   : {', '.join(found.missing_required)} — required")


def cmd_inspect(args: argparse.Namespace) -> int:
    found = inspect(args.file, rows=args.rows)
    if args.json:
        print(
            json.dumps(
                {
                    "file_path": found.file_path,
                    "resolved": str(found.path),
                    "delimiter": escape_delim(found.delimiter),
                    "header": found.header,
                    "mapping": found.mapping,
                    "unmapped": found.unmapped_header,
                    "missing_required": found.missing_required,
                    "notes": found.notes,
                    "gene_id_mode": infer_gene_id_mode(found.sample("phenotype_id_col")),
                },
                indent=2,
            )
        )
        return 0
    _print_inspection(found)
    print("\nfirst rows:")
    for row in found.rows:
        print("  " + " | ".join(v[:18] for v in row[: len(found.header)]))
    return 1 if found.missing_required else 0


def _column_fields(found: Inspection) -> dict[str, str]:
    return {
        "file_path": found.file_path,
        "delimiter": escape_delim(found.delimiter),
        **{slot: found.mapping.get(slot, "") for slot in SYNONYMS},
    }


def cmd_add_gwas(args: argparse.Namespace) -> int:
    found = inspect(args.file)
    if found.missing_required and not args.force:
        _print_inspection(found)
        print("\nrefusing to add — pass --force to record it anyway", file=sys.stderr)
        return 1
    fields = _column_fields(found)
    fields.pop("phenotype_id_col", None)

    meta = {"accession": args.accession, "datasource": "GWAS Catalog", "type": "quant"}
    if args.metadata:
        record = find_record(load_store(args.metadata), "gwas", args.accession)
        meta = from_store(record, GWAS_FROM_STORE)
    # Anything given on the command line wins over the store.
    overrides = {
        "trait": args.trait, "datasource": args.datasource, "population": args.population,
        "type": args.type, "url": args.url,
        "sample_size": str(args.sample_size) if args.sample_size is not None else "",
    }
    meta.update({k: v for k, v in overrides.items() if v})
    meta["accession"] = args.accession

    missing = [f for f in GWAS_FROM_STORE if not meta.get(f)]
    if missing and not args.force:
        print(f"missing metadata: {', '.join(missing)}", file=sys.stderr)
        print("supply it with flags, or record it with --save-metadata upstream", file=sys.stderr)
        return 1
    row = {**{f: meta.get(f, "") for f in GWAS_FROM_STORE}, **fields}
    action = upsert(args.manifest, GWAS_COLUMNS, GWAS_KEY, row)
    print(f"{action}: {args.accession} in {args.manifest}")
    for note in found.notes:
        print(f"  note: {note}")
    return 0


def cmd_add_qtl(args: argparse.Namespace) -> int:
    found = inspect(args.file)
    if found.missing_required and not args.force:
        _print_inspection(found)
        print("\nrefusing to add — pass --force to record it anyway", file=sys.stderr)
        return 1
    mode = args.gene_id_mode
    if mode is None:
        mode = infer_gene_id_mode(found.sample("phenotype_id_col"))
    meta: dict[str, str] = {}
    if args.metadata:
        key = args.key or f"{args.dataset}|{args.qtl_type}|{args.biocontext}"
        record = find_record(load_store(args.metadata), "qtl", key)
        meta = from_store(record, QTL_FROM_STORE)
    overrides = {
        "dataset": args.dataset, "qtl_type": args.qtl_type, "biocontext": args.biocontext,
        "level_1_context": args.level_1_context, "level_2_context": args.level_2_context,
        "population": args.population, "url": args.url,
        "sample_size": str(args.sample_size) if args.sample_size is not None else "",
    }
    meta.update({k: v for k, v in overrides.items() if v})
    meta.setdefault("level_1_context", "")
    if not meta["level_1_context"]:
        meta["level_1_context"] = meta.get("biocontext", "")

    # level_2_context is legitimately blank for bulk tissue, so it is not required.
    missing = [f for f in QTL_FROM_STORE if not meta.get(f) and f != "level_2_context"]
    if missing and not args.force:
        print(f"missing metadata: {', '.join(missing)}", file=sys.stderr)
        print("supply it with flags, or record it with --save-metadata upstream", file=sys.stderr)
        return 1
    row = {
        **{f: meta.get(f, "") for f in QTL_FROM_STORE},
        "gene_id_mode": mode,
        **_column_fields(found),
    }
    action = upsert(args.manifest, QTL_COLUMNS, QTL_KEY, row)
    print(f"{action}: {args.dataset}/{args.qtl_type}/{args.biocontext} in {args.manifest}")
    print(f"  gene_id_mode: {mode or '(blank)'}")
    for note in found.notes:
        print(f"  note: {note}")
    return 0


# ── filling the review table ─────────────────────────────────────────────────
#
# Stage 4. download_qtl leaves local_path and download_status=downloaded on every
# row it fetched; this reads the head of each of those files and records the layout
# next to the dataset it belongs to. Columns this stage owns:

LAYOUT_COLUMNS = (
    "delimiter", "n_columns", "chrom_col", "position_col", "ref_col", "alt_col",
    "beta_col", "se_col", "pval_col", "rsid_col", "maf_col", "phenotype_id_col",
    "layout_status", "missing_columns",
)
TABLE_REQUIRED = ("record_id", "download_status", "local_path")


def _table_delimiter(path: Path) -> str:
    return "," if path.suffix.casefold() == ".csv" else "\t"


def read_review_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=_table_delimiter(path))
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    if not fields:
        raise ValueError(f"table has no header: {path}")
    missing = [c for c in TABLE_REQUIRED if c not in fields]
    if missing:
        raise ValueError(f"{path} has not been through download_qtl; missing: {', '.join(missing)}")
    return fields, rows


def write_review_table(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=_table_delimiter(path))
        writer.writeheader()
        writer.writerows(rows)


def fill_table(table: Path, *, rows_to_read: int, force: bool) -> dict[str, int]:
    """Record delimiter, column mapping and readiness for every downloaded file."""
    fields, rows = read_review_table(table)
    fields = fields + [c for c in LAYOUT_COLUMNS if c not in fields]
    for row in rows:
        for column in LAYOUT_COLUMNS:
            row.setdefault(column, "")

    counts = {"complete": 0, "missing-columns": 0, "unreadable": 0, "skipped": 0}
    for row in rows:
        path_value = row.get("local_path", "").strip()
        if row.get("download_status", "") != "downloaded" or not path_value:
            counts["skipped"] += 1
            continue
        if row.get("layout_status", "") and not force:
            counts[row["layout_status"]] = counts.get(row["layout_status"], 0) + 1
            continue
        try:
            found = inspect(path_value, rows=rows_to_read)
        except (FileNotFoundError, ValueError, OSError) as exc:
            row["layout_status"] = "unreadable"
            row["missing_columns"] = f"{type(exc).__name__}: {exc}"
            counts["unreadable"] += 1
            continue
        row["delimiter"] = escape_delim(found.delimiter)
        row["n_columns"] = str(len(found.header))
        for slot in SYNONYMS:
            if slot in LAYOUT_COLUMNS:
                row[slot] = found.mapping.get(slot, "")
        row["missing_columns"] = ";".join(found.missing_required)
        row["layout_status"] = "missing-columns" if found.missing_required else "complete"
        counts[row["layout_status"]] += 1
    write_review_table(table, fields, rows)
    return counts


def cmd_fill_table(args: argparse.Namespace) -> int:
    counts = fill_table(args.table, rows_to_read=args.rows, force=args.force)
    print(f"{args.table}: {counts}")
    if counts.get("missing-columns"):
        print(
            "rows marked missing-columns lack one of chrom/position/ref/alt/beta/pval — "
            "find the right file or record why it cannot be used; do not force them in",
            file=sys.stderr,
        )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    columns = GWAS_COLUMNS if args.kind == "gwas" else QTL_COLUMNS
    rows = read_manifest(args.manifest, columns)
    if not rows:
        print(f"{args.manifest} has no rows", file=sys.stderr)
        return 1
    problems = 0
    for row in rows:
        label = row.get("accession") or f"{row.get('dataset')}/{row.get('biocontext')}"
        issues: list[str] = []
        try:
            found = inspect(row["file_path"])
        except (FileNotFoundError, ValueError) as exc:
            print(f"  FAIL {label}: {exc}")
            problems += 1
            continue
        for slot in SYNONYMS:
            recorded = row.get(slot, "")
            if recorded and recorded not in found.header:
                issues.append(f"{slot}={recorded!r} is not a column in the file")
        if escape_delim(found.delimiter) != row.get("delimiter"):
            issues.append(
                f"delimiter {row.get('delimiter')!r} but the file looks "
                f"{escape_delim(found.delimiter)!r}"
            )
        if not str(row.get("sample_size", "")).isdigit():
            issues.append("sample_size is not a number")
        if issues:
            problems += 1
            print(f"  FAIL {label}")
            for issue in issues:
                print(f"       {issue}")
        else:
            print(f"  ok   {label}")
    print(f"\n{len(rows) - problems}/{len(rows)} rows valid")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("inspect", help="peek at a file and propose a column mapping")
    s.add_argument("file")
    s.add_argument("--rows", type=int, default=3)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser(
        "fill-table", help="fill a review table's layout columns from the downloaded files"
    )
    s.add_argument("table", type=Path, help="the review table download_qtl updated")
    s.add_argument("--rows", type=int, default=5, help="data rows to read per file")
    s.add_argument("--force", action="store_true", help="re-inspect rows already filled")
    s.set_defaults(func=cmd_fill_table)

    s = sub.add_parser("add-gwas", help="record a GWAS file in gwas_manifest.tsv")
    s.add_argument("file")
    s.add_argument("--accession", required=True)
    s.add_argument("--metadata", type=Path, help="shared metadata store (JSONL) to read from")
    s.add_argument("--trait", default="", help="underscored, e.g. Basophil_count")
    s.add_argument("--datasource", default="")
    s.add_argument("--population", default="", help="EUR, EAS, AFR, SAS, AMR, ALL")
    s.add_argument("--type", default="", choices=["", "quant", "cc"])
    s.add_argument("--sample-size", type=int, default=None)
    s.add_argument("--url", default="")
    s.add_argument("--manifest", type=Path, default=Path("gwas_manifest.tsv"))
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_add_gwas)

    s = sub.add_parser("add-qtl", help="record a QTL file in qtl_manifest.tsv")
    s.add_argument("file")
    s.add_argument("--dataset", required=True, help="e.g. GTEx_v10, CIMA, Tenk10k")
    s.add_argument("--qtl-type", required=True, help="eQTL, sQTL, pQTL, caQTL, mQTL")
    s.add_argument("--biocontext", required=True, help="the specific context, e.g. cMono_CD14")
    s.add_argument("--metadata", type=Path, help="shared metadata store (JSONL) to read from")
    s.add_argument("--key", default="", help="store key, if it differs from dataset|type|context")
    s.add_argument("--level-1-context", default="", help="broad tissue; defaults to biocontext")
    s.add_argument("--level-2-context", default="", help="cell type, blank for bulk tissue")
    s.add_argument("--population", default="")
    s.add_argument("--sample-size", type=int, default=None)
    s.add_argument(
        "--gene-id-mode",
        default=None,
        choices=["self", "phenotype_last_segment", ""],
        help="default: inferred from the phenotype_id value",
    )
    s.add_argument("--url", default="")
    s.add_argument("--manifest", type=Path, default=Path("qtl_manifest.tsv"))
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_add_qtl)

    s = sub.add_parser("validate", help="re-check a manifest against the files")
    s.add_argument("kind", choices=["gwas", "qtl"])
    s.add_argument("--manifest", type=Path, required=True)
    s.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    try:
        result: int = args.func(args)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
