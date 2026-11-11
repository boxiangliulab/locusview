"""Tests for the constrained local-tool layer of qtl-data-agent and its four pipeline skills."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

AGENT_PATH = Path(__file__).resolve().parents[1] / "qtl-data-agent" / "agent.py"
SPEC = importlib.util.spec_from_file_location("qtl_data_agent", AGENT_PATH)
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = agent
SPEC.loader.exec_module(agent)

SKILLS_DIR = agent.SKILLS_DIR
discover_skills = agent.discover_skills
read_skill = agent.read_skill
run_skill_script = agent.run_skill_script

# The columns qtl-data-finder writes; the later stages append their own.
REVIEW_COLUMNS = (
    "record_id", "publication_title", "publication_url", "doi", "pmid", "first_author",
    "authors", "year", "journal", "contact_email", "qtl_type", "qtl_context", "population",
    "sample_size", "dataset_name", "download_url", "access_route", "direct_download",
    "extraction_note", "evidence_source", "search_terms", "search_date",
)


def write_table(path: Path, rows: list[dict[str, str]], columns: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def review_row(**values: str) -> dict[str, str]:
    row = dict.fromkeys(REVIEW_COLUMNS, "")
    row.update(access_route="unknown", direct_download="unknown", search_date="2026-09-01")
    row.update(values)
    return row


def test_discovers_all_repository_skills() -> None:
    assert set(discover_skills()) == {
        "download-qtl",
        "gwas-catalog-lookup",
        "qtl-data-finder",
        "qtl-record-verifier",
        "sumstats-manifest",
    }


def test_reads_selected_skill() -> None:
    text = read_skill(discover_skills(), "qtl-data-finder")
    assert "Search the published literature" in text
    assert "qtlliteraturereview" in text
    assert "download_url" in text


def test_rejects_script_path_escape() -> None:
    with pytest.raises(ValueError, match="inside the selected skill"):
        run_skill_script(discover_skills(), "qtl-data-finder", "../../agent.py", [])


def test_runs_only_bundled_python_script() -> None:
    result = run_skill_script(
        discover_skills(), "qtl-data-finder", "find_qtl.py", ["--help"], timeout=10
    )
    assert result["exit_code"] == 0
    assert "review" in result["stdout"]
    assert "update" in result["stdout"]


def test_default_skills_directory_is_inside_qtl_data_agent() -> None:
    assert SKILLS_DIR.parent.name == "qtl-data-agent"


def test_agent_instructions_include_the_complete_qtl_pipeline_objective() -> None:
    instructions = agent._instructions(discover_skills())
    assert "broadest practical, evidence-backed inventory" in instructions
    assert "qtlliteraturereview" in instructions
    assert "keeps the earliest published paper" in instructions
    assert "never use --force" in instructions
    assert "sending mail" in instructions


def test_finder_update_records_extracted_fields_and_rejects_bad_values(tmp_path: Path) -> None:
    table = tmp_path / "qtlliteraturereview-2026-09-01.tsv"
    write_table(table, [review_row(record_id="1", publication_title="OneK1K")], REVIEW_COLUMNS)
    skills = discover_skills()

    accepted = run_skill_script(
        skills,
        "qtl-data-finder",
        "find_qtl.py",
        [
            "update", str(table), "1",
            "--set", "dataset_name=OneK1K",
            "--set", "qtl_context=PBMC_CD4_naive",
            "--set", "sample_size=982",
            "--set", "download_url=https://data.example/cd4.tsv.gz",
            "--set", "access_route=direct",
            "--set", "direct_download=yes",
        ],
        timeout=10,
    )
    assert accepted["exit_code"] == 0
    row = read_rows(table)[0]
    assert row["sample_size"] == "982"
    assert row["access_route"] == "direct"

    # A publication page is not a statistics file, and the field list is closed.
    for assignment, message in (
        ("download_url=https://doi.org/10.1/x", "publication page"),
        ("download_url=ftp://data.example/x.tsv", "HTTP(S) URL"),
        ("sample_size=982 donors", "donor count"),
        ("verify_status=verified", "cannot set"),
        ("access_route=maybe", "access_route must be"),
    ):
        rejected = run_skill_script(
            skills,
            "qtl-data-finder",
            "find_qtl.py",
            ["update", str(table), "1", "--set", assignment],
            timeout=10,
        )
        assert rejected["exit_code"] == 1, assignment
        assert message in rejected["stderr"], assignment


def test_verifier_keeps_the_earliest_paper_but_not_distinct_contexts(tmp_path: Path) -> None:
    table = tmp_path / "review.tsv"
    output = tmp_path / "review.dedup.tsv"
    report = tmp_path / "review.duplicates.tsv"
    write_table(
        table,
        [
            review_row(
                record_id="1", publication_title="OneK1K resource", year="2021", pmid="1002",
                dataset_name="OneK1K", qtl_type="eQTL", qtl_context="CD4_naive",
                sample_size="982", download_url="https://data.example/cd4.tsv.gz",
                access_route="direct", direct_download="yes",
            ),
            review_row(
                record_id="2", publication_title="OneK1K first release", year="2019", pmid="1001",
                dataset_name="OneK1K", qtl_type="eQTL", qtl_context="CD4_naive",
                sample_size="982",
            ),
            review_row(
                record_id="3", publication_title="GTEx v10", year="2024", pmid="2001",
                dataset_name="GTEx_v10", qtl_type="eQTL", qtl_context="Lung", sample_size="838",
            ),
        ],
        REVIEW_COLUMNS,
    )

    result = run_skill_script(
        discover_skills(),
        "qtl-record-verifier",
        "verify_qtl.py",
        ["dedupe", str(table), "--out", str(output), "--report", str(report)],
        timeout=10,
    )

    assert result["exit_code"] == 0
    assert "grouped 3 rows into 2 datasets" in result["stdout"]
    rows = {row["record_id"]: row for row in read_rows(output)}
    # The 2019 paper is the one kept; the 2021 re-release becomes its duplicate.
    assert rows["2"]["verify_status"] == "unresolved"
    assert rows["1"]["verify_status"] == "duplicate"
    assert rows["1"]["duplicate_of"] == "2"
    # A blank on the kept row is filled from the duplicate, and the fill is explained.
    assert rows["2"]["download_url"] == "https://data.example/cd4.tsv.gz"
    assert "filled from duplicate record 1" in rows["2"]["verifier_note"]
    # A different dataset is never merged in.
    assert rows["3"]["verify_status"] == "unresolved"
    assert "url:data.example/cd4.tsv.gz" in report.read_text(encoding="utf-8")


def test_verifier_validate_requires_a_decision_and_writes_the_ready_rows(tmp_path: Path) -> None:
    table = tmp_path / "reviewed.tsv"
    ready = tmp_path / "ready.tsv"
    columns = (
        *REVIEW_COLUMNS,
        "verify_status", "duplicate_of", "url_status", "url_http_code", "url_content_type",
        "url_bytes", "access_action", "verified_date", "verifier_note",
    )
    rows = [
        review_row(
            record_id="1", publication_title="Direct eQTL", year="2020", qtl_type="eQTL",
            qtl_context="Whole_Blood", sample_size="500",
            download_url="https://data.example/wb.tsv.gz", access_route="direct",
            direct_download="yes",
        ),
        review_row(
            record_id="2", publication_title="On request", year="2021", qtl_type="pQTL",
            qtl_context="islet", sample_size="120", access_route="request",
            direct_download="no", contact_email="author@example.edu",
        ),
    ]
    rows[0].update(
        verify_status="verified", url_status="ok", url_http_code="200", access_action="none",
        verified_date="2026-09-01",
    )
    rows[1].update(verify_status="unresolved", verified_date="2026-09-01")
    write_table(table, rows, columns)
    skills = discover_skills()

    unfinished = run_skill_script(
        skills, "qtl-record-verifier", "verify_qtl.py", ["validate", str(table)], timeout=10
    )
    assert unfinished["exit_code"] == 1
    assert "still unresolved" in unfinished["stderr"]

    rows[1].update(
        verify_status="needs-request",
        access_action="email-author",
        verifier_note="Data availability: pQTL statistics available from the authors on request.",
    )
    write_table(table, rows, columns)
    finished = run_skill_script(
        skills,
        "qtl-record-verifier",
        "verify_qtl.py",
        ["validate", str(table), "--ready-out", str(ready)],
        timeout=10,
    )
    assert finished["exit_code"] == 0
    assert "1 are ready to download" in finished["stdout"]
    assert [row["record_id"] for row in read_rows(ready)] == ["1"]


def test_verifier_keeps_public_bucket_out_of_request_and_download_queues(tmp_path: Path) -> None:
    table = tmp_path / "reviewed.tsv"
    ready = tmp_path / "ready.tsv"
    columns = (
        *REVIEW_COLUMNS,
        "verify_status", "duplicate_of", "url_status", "url_http_code", "url_content_type",
        "url_bytes", "access_action", "verified_date", "verifier_note",
    )
    row = review_row(
        record_id="1973", publication_title="Public pQTL bucket", year="2026",
        qtl_type="pQTL", qtl_context="plasma", population="SAS", sample_size="1413",
        download_url="https://example.org/public-bucket/", access_route="portal",
        direct_download="no",
    )
    row.update(
        verify_status="public-access", access_action="open-record", url_status="ok",
        verified_date="2026-09-07", verifier_note="Anonymous public bucket; no application.",
    )
    write_table(table, [row], columns)

    result = run_skill_script(
        discover_skills(), "qtl-record-verifier", "verify_qtl.py",
        ["validate", str(table), "--ready-out", str(ready)], timeout=10,
    )

    assert result["exit_code"] == 0
    assert "0 are ready to download" in result["stdout"]
    assert read_rows(ready) == []


def test_verifier_accepts_documented_public_bucket_that_is_actually_blocked(tmp_path: Path) -> None:
    table = tmp_path / "reviewed.tsv"
    columns = (
        *REVIEW_COLUMNS,
        "verify_status", "duplicate_of", "url_status", "url_http_code", "url_content_type",
        "url_bytes", "access_action", "verified_date", "verifier_note",
    )
    row = review_row(
        record_id="1973", publication_title="Blocked pQTL bucket", year="2026",
        qtl_type="pQTL", qtl_context="plasma", sample_size="1413",
        download_url="https://example.org/public-bucket/", access_route="blocked",
        direct_download="no", contact_email="maintainer@example.org",
    )
    row.update(
        verify_status="needs-request", access_action="repair-access", url_status="dead",
        url_http_code="403-vpcServiceControls", verified_date="2026-09-07",
        verifier_note="README says public; actual object read is policy-blocked.",
    )
    write_table(table, [row], columns)

    result = run_skill_script(
        discover_skills(), "qtl-record-verifier", "verify_qtl.py",
        ["validate", str(table)], timeout=10,
    )

    assert result["exit_code"] == 0


def test_download_qtl_fetches_nothing_the_verifier_did_not_clear(tmp_path: Path) -> None:
    table = tmp_path / "reviewed.tsv"
    columns = (
        *REVIEW_COLUMNS,
        "verify_status", "duplicate_of", "url_status", "url_http_code", "url_content_type",
        "url_bytes", "access_action", "verified_date", "verifier_note",
    )
    rows = [
        review_row(
            record_id="1", publication_title="Portal only", access_route="portal",
            direct_download="no", download_url="https://portal.example/browse",
        ),
        review_row(
            record_id="2", publication_title="Unchecked URL", access_route="direct",
            direct_download="yes", download_url="https://data.example/x.tsv.gz",
        ),
    ]
    rows[0].update(verify_status="needs-request", access_action="export-portal", url_status="ok")
    rows[1].update(verify_status="verified", access_action="none", url_status="not-checked")
    write_table(table, rows, columns)

    result = run_skill_script(
        discover_skills(),
        "download-qtl",
        "download_qtl.py",
        ["download", str(table), "--out-dir", str(tmp_path / "data")],
        timeout=10,
    )

    assert result["exit_code"] == 0
    assert "'downloaded': 0" not in result["stdout"]
    assert "'skipped': 2" in result["stdout"]
    assert not (tmp_path / "data").exists()
    skipped = {row["record_id"]: row["download_error"] for row in read_rows(table)}
    assert "not verified" in skipped["1"]
    assert "confirmed to resolve" in skipped["2"]


def test_fill_table_records_the_layout_and_flags_a_missing_required_column(
    tmp_path: Path,
) -> None:
    usable = tmp_path / "usable.tsv"
    usable.write_text(
        "chromosome\tposition\tother_allele\teffect_allele\tbeta\tp_value\tmolecular_trait_id\n"
        "10\t100\tA\tC\t-0.16\t1e-8\tENSG00000261456.6\n",
        encoding="utf-8",
    )
    unusable = tmp_path / "unusable.tsv"
    unusable.write_text("chrom\tpos\trsid\n1\t10\trs1\n", encoding="utf-8")

    table = tmp_path / "downloaded.tsv"
    columns = (
        *REVIEW_COLUMNS,
        "verify_status", "download_status", "local_path", "file_bytes", "download_date",
        "download_error",
    )
    rows = [
        review_row(record_id="1", publication_title="Usable"),
        review_row(record_id="2", publication_title="No beta"),
        review_row(record_id="3", publication_title="Never downloaded"),
    ]
    rows[0].update(verify_status="verified", download_status="downloaded", local_path=str(usable))
    rows[1].update(verify_status="verified", download_status="downloaded", local_path=str(unusable))
    rows[2].update(verify_status="needs-request", download_status="skipped")
    write_table(table, rows, columns)

    result = run_skill_script(
        discover_skills(),
        "sumstats-manifest",
        "manifest.py",
        ["fill-table", str(table)],
        timeout=20,
    )

    assert result["exit_code"] == 0
    filled = {row["record_id"]: row for row in read_rows(table)}
    assert filled["1"]["layout_status"] == "complete"
    assert filled["1"]["beta_col"] == "beta"
    assert filled["1"]["phenotype_id_col"] == "molecular_trait_id"
    assert filled["1"]["delimiter"] == "\\t"
    assert filled["2"]["layout_status"] == "missing-columns"
    assert "beta_col" in filled["2"]["missing_columns"]
    # A row that was never downloaded is skipped, not guessed at.
    assert filled["3"]["layout_status"] == ""


def test_pipeline_resume_skips_rows_that_already_have_a_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline_root = tmp_path / "qtl-data-agent"
    pipeline_root.mkdir()
    monkeypatch.setattr(agent, "ROOT", pipeline_root)
    table = tmp_path / "review.tsv"
    write_table(
        table,
        [
            dict(review_row(record_id="1"), **{"verify_status": "verified"}),
            dict(review_row(record_id="2"), **{"verify_status": ""}),
        ],
        (*REVIEW_COLUMNS, "verify_status"),
    )
    prompts: list[str] = []

    def fake_run_agent(prompt: str, **_: object) -> str:
        prompts.append(prompt)
        return "done"

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)
    reports = agent.run_pipeline(
        table,
        download_dir=tmp_path / "downloads",
        manifest=tmp_path / "qtl_manifest.tsv",
        batch_size=2,
        model="test-model",
        api_key="test-key",
    )
    assert reports == ["done"]
    assert "[1]" in prompts[0]
