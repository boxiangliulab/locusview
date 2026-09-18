#!/usr/bin/env python3
"""LLM agent that discovers and runs the repository's data-search skills.

The agent uses the OpenAI Responses API, built-in web search, and three constrained local tools:
read a skill, run a script bundled with a skill, and read a batch of rows from a review table.
Pipeline state lives in the review table the skills read and write, not in the agent. The agent
never executes model-authored shell commands.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SKILLS_DIR = ROOT / "skills"
PIPELINE_PROMPT_PATH = ROOT / "prompts" / "qtl_data_pipeline.md"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_API_BASE = "https://api.openai.com/v1"
MAX_TOOL_ROUNDS = 30
MAX_TOOL_OUTPUT = 80_000


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in {"name", "description"}:
            values[key.strip()] = value.strip()
    return values


def discover_skills(skills_dir: Path = SKILLS_DIR) -> dict[str, Skill]:
    """Discover valid one-directory-deep skills without importing or executing them."""
    found: dict[str, Skill] = {}
    if not skills_dir.is_dir():
        return found
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        metadata = _frontmatter(text)
        name = metadata.get("name", skill_file.parent.name)
        if name != skill_file.parent.name:
            continue
        found[name] = Skill(name, metadata.get("description", ""), skill_file.parent)
    return found


def _skill(skills: dict[str, Skill], name: str) -> Skill:
    try:
        return skills[name]
    except KeyError as exc:
        raise ValueError(f"unknown skill {name!r}; available: {', '.join(skills)}") from exc


def read_skill(skills: dict[str, Skill], name: str) -> str:
    return (_skill(skills, name).path / "SKILL.md").read_text(encoding="utf-8")


def run_skill_script(
    skills: dict[str, Skill], name: str, script: str, args: list[str], timeout: int = 900
) -> dict[str, Any]:
    """Run only a .py file physically contained in the selected skill's scripts directory."""
    skill = _skill(skills, name)
    scripts_dir = (skill.path / "scripts").resolve()
    candidate = (scripts_dir / script).resolve()
    if candidate.suffix != ".py" or not candidate.is_relative_to(scripts_dir):
        raise ValueError("script must be a .py file inside the selected skill's scripts directory")
    if not candidate.is_file():
        raise ValueError(f"skill script does not exist: {script}")
    completed = subprocess.run(
        [sys.executable, str(candidate), *args],
        cwd=ROOT.parent,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    stdout = completed.stdout[-MAX_TOOL_OUTPUT:]
    stderr = completed.stderr[-MAX_TOOL_OUTPUT:]
    return {"exit_code": completed.returncode, "stdout": stdout, "stderr": stderr}


def _workspace_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = (ROOT.parent / path).resolve() if not path.is_absolute() else path.resolve()
    if not resolved.is_relative_to(ROOT.parent.resolve()):
        raise ValueError("pipeline paths must stay inside the locusview repository")
    return resolved


def read_candidate_batch(path: str, offset: int, limit: int) -> dict[str, Any]:
    source = _workspace_path(path)
    delimiter = "," if source.suffix.casefold() == ".csv" else "\t"
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter=delimiter))
    selected = rows[offset : offset + min(max(limit, 1), 25)]
    return {
        "total": len(rows),
        "offset": offset,
        "rows": [
            row if row.get("record_id") else dict(row, record_id=str(offset + index))
            for index, row in enumerate(selected)
        ],
    }


def _tools() -> list[dict[str, Any]]:
    """Web search, plus the constrained local tools. The skills own everything they persist."""
    return [
        {"type": "web_search"},
        {
            "type": "function",
            "name": "read_skill",
            "description": "Read the complete instructions for one installed local skill.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "run_skill_script",
            "description": (
                "Run a Python script bundled with a skill. Read that skill first and pass each "
                "CLI token as one element of args. Arbitrary shell commands are not supported."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "script": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "script", "args"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "read_candidate_batch",
            "description": "Read at most 25 rows from a repository review table (TSV/CSV).",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                },
                "required": ["path", "offset", "limit"],
                "additionalProperties": False,
            },
        },
    ]


def pipeline_objective() -> str:
    return PIPELINE_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _instructions(skills: dict[str, Skill]) -> str:
    catalog = "\n".join(f"- {s.name}: {s.description}" for s in skills.values())
    return f"""You are the locusview data-search agent. Find published, usable QTL/GWAS data
thoroughly and produce evidence-backed results. Available local skills:

{catalog}

Standing QTL pipeline objective:

{pipeline_objective()}

Select relevant skills from their descriptions, call read_skill before using each one, and follow
its complete instructions. Every skill's state lives in the review table it reads and writes, so
run its scripts through run_skill_script rather than keeping decisions in your own reasoning.

Use web search for current literature and official repository pages, and prefer primary papers and
official data repositories. Never claim a URL is summary statistics until it has been verified;
distinguish direct downloads from raw data, controlled access, portal-only access and supplements.
An anonymously accessible repository, bucket or portal is `public-access`, not `needs-request`;
reserve the request queue for an email, application, approval, or genuinely gated export.
Treat a resource as anonymously accessible only after reading an actual object/listing. If its
documentation says public but the object store returns 401/403 or a policy denial, record
`access_route=blocked`, `verify_status=needs-request`, and `access_action=repair-access`.
Deduplicate datasets with qtl-record-verifier `dedupe`, which keeps the earliest published paper
per dataset — do not collapse rows that differ by tissue, cell type, quantification method,
population, release or QTL type merely because they cite the same paper. Record donor count, never
cell count, as the sample size.

For inventory requests, return a Markdown table with QTL type, dataset, biological context,
population, donor sample size, verified download URL, access route, paper URL, DOI/PMID and the
evidence for each. State the search scope, the date checked, unresolved candidates, and the limits
of a best-effort search.

For a full pipeline run, work the review table stage by stage: qtl-data-finder to search and record
what each paper says, qtl-record-verifier to deduplicate, check URLs and decide every row,
download-qtl to fetch only rows it cleared, and sumstats-manifest to read the downloaded files and
register them. Never fetch a URL the verifier did not clear, and never use --force to hide a
missing required column. For non-public datasets, record the contact, the application route and the
human action required, and remind the operator to carry it out. Drafting a request email is
allowed; sending mail or taking any other irreversible external action is not."""


class ResponsesClient:
    def __init__(self, api_key: str, api_base: str = DEFAULT_API_BASE) -> None:
        self.api_key = api_key
        self.url = api_base.rstrip("/") + "/responses"

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API returned HTTP {exc.code}: {detail}") from exc


def _function_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in response.get("output", []) if item.get("type") == "function_call"]


def _output_text(response: dict[str, Any]) -> str:
    chunks = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))
    return "\n".join(chunks).strip()


def run_agent(prompt: str, *, model: str, api_key: str, skills_dir: Path = SKILLS_DIR) -> str:
    skills = discover_skills(skills_dir)
    if not skills:
        raise RuntimeError(f"no skills found under {skills_dir}")
    client = ResponsesClient(api_key, os.environ.get("OPENAI_BASE_URL", DEFAULT_API_BASE))
    payload: dict[str, Any] = {
        "model": model,
        "instructions": _instructions(skills),
        "input": prompt,
        "tools": _tools(),
        "include": ["web_search_call.action.sources"],
    }
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.create(payload)
        calls = _function_calls(response)
        if not calls:
            text = _output_text(response)
            if not text:
                status = response.get("status")
                raise RuntimeError(f"model returned no final text (status={status})")
            return text
        outputs = []
        for call in calls:
            try:
                arguments = json.loads(call.get("arguments") or "{}")
                if call["name"] == "read_skill":
                    result: Any = read_skill(skills, arguments["name"])
                elif call["name"] == "run_skill_script":
                    result = run_skill_script(
                        skills, arguments["name"], arguments["script"], arguments["args"]
                    )
                elif call["name"] == "read_candidate_batch":
                    result = read_candidate_batch(**arguments)
                else:
                    raise ValueError(f"unsupported function {call['name']!r}")
                output = (
                    result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                )
            except Exception as exc:  # return tool errors to the model so it can recover
                output = json.dumps({"error": str(exc)}, ensure_ascii=False)
            outputs.append(
                {"type": "function_call_output", "call_id": call["call_id"], "output": output}
            )
        payload = {
            "model": model,
            "instructions": _instructions(skills),
            "previous_response_id": response["id"],
            "input": outputs,
            "tools": _tools(),
            "include": ["web_search_call.action.sources"],
        }
    raise RuntimeError(f"agent exceeded {MAX_TOOL_ROUNDS} local-tool rounds")


def pending_rows(table: Path, batch_size: int) -> list[list[int]]:
    """Rows still waiting on a decision, in batches. verify_status is written by the skills."""
    source = _workspace_path(table)
    delimiter = "," if source.suffix.casefold() == ".csv" else "\t"
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter=delimiter))
    pending = [
        index
        for index, row in enumerate(rows)
        if row.get("verify_status", "").strip() in ("", "unresolved")
    ]
    return [pending[start : start + batch_size] for start in range(0, len(pending), batch_size)]


def run_pipeline(
    table: Path,
    *,
    download_dir: Path,
    manifest: Path,
    batch_size: int,
    model: str,
    api_key: str,
) -> list[str]:
    """Work through an existing review table in batches, resuming from its own state."""
    reports: list[str] = []
    for batch in pending_rows(table, batch_size):
        prompt = f"""Follow the standing QTL pipeline objective for rows {batch} (zero-based) of
{table}. Read only that batch with read_candidate_batch. For each row: read the paper, record what
it says with qtl-data-finder `update`, then decide it with qtl-record-verifier — dedupe, check-urls
and a verify_status of verified, needs-request, rejected or duplicate, with verified_date set.
Then run download-qtl on the table for the rows that qualify, and sumstats-manifest `fill-table`
followed by `add-qtl` into {manifest} for what downloaded. Files go to {download_dir}. Do not use
--force. Leave no row unresolved, and report every failure so a later run can retry it."""
        reports.append(run_agent(prompt, model=model, api_key=api_key))
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="data-search request for the agent")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--out", type=Path, help="also save the final Markdown response")
    parser.add_argument("--list-skills", action="store_true")
    parser.add_argument("--show-pipeline-prompt", action="store_true")
    parser.add_argument(
        "--pipeline",
        type=Path,
        help="work through a qtlliteraturereview table, resuming from its verify_status column",
    )
    parser.add_argument("--download-dir", type=Path, default=Path("data/qtl-verified"))
    parser.add_argument("--qtl-manifest", type=Path, default=Path("qtl_manifest.tsv"))
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()

    if args.list_skills:
        for skill in discover_skills().values():
            print(f"{skill.name}\t{skill.description}")
        return 0
    if args.show_pipeline_prompt:
        print(pipeline_objective())
        return 0
    if not args.prompt and not args.pipeline:
        parser.error("prompt is required unless --list-skills is used")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        parser.error("OPENAI_API_KEY is required")

    if args.pipeline:
        if not 1 <= args.batch_size <= 25:
            parser.error("--batch-size must be between 1 and 25")
        reports = run_pipeline(
            args.pipeline,
            download_dir=args.download_dir,
            manifest=args.qtl_manifest,
            batch_size=args.batch_size,
            model=args.model,
            api_key=api_key,
        )
        answer = "\n\n".join(reports)
    else:
        answer = run_agent(args.prompt, model=args.model, api_key=api_key)
    print(answer)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(answer + "\n", encoding="utf-8")
        print(f"saved report to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
