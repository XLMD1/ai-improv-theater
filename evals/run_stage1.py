"""Phase 1 reproducible rules/legacy tasks. No providers; failures keep the denominator."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
MANIFEST = ROOT / "evals" / "cases" / "stage1.json"


def validate_database_url(value: str):
    try:
        url = make_url(value)
        if url.get_backend_name() == "postgresql" and (url.database or "").endswith("_test"):
            return url
    except Exception:
        pass
    raise ValueError("dedicated_postgresql_test_database_required")


def summarize(results: list[dict]) -> dict:
    if not results:
        raise ValueError("empty_suite")
    counts = {status: sum(row["status"] == status for row in results)
              for status in ("succeeded", "failed", "error", "skipped")}
    if sum(counts.values()) != len(results):
        raise ValueError("unknown_case_status")
    return {"total": len(results), **counts, "task_success_rate": counts["succeeded"] / len(results)}


def execute_case(case: dict, output: Path, environment: dict) -> dict:
    started = time.monotonic()
    result = {"id": case["id"], "status": "error", "error_code": None, "checks_run": 0}
    artifact = output / (case["id"] + ".json")
    child_env = dict(environment)
    child_env.pop("PYTEST_ADDOPTS", None)
    child_env["PYTHONPATH"] = str(ROOT) + os.pathsep + child_env.get("PYTHONPATH", "")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", case["test"], "-q", "--override-ini=addopts=",
             "-p", "no:cacheprovider", "-p", "evals.pytest_status", "--stage1-result=" + str(artifact)],
            cwd=BACKEND, env=child_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=case["timeout_seconds"], check=False,
        )
        counts = json.loads(artifact.read_text(encoding="utf-8"))
        required = {"passed", "failed", "error", "skipped", "collected", "deselected", "exit_code"}
        if (set(counts) != required or any(type(value) is not int or value < 0 for value in counts.values())):
            raise ValueError("invalid_test_result")
        elif counts["deselected"]:
            result["error_code"] = "required_checks_deselected"
        elif counts["error"]:
            result["error_code"] = "test_error"
        elif counts["failed"]:
            result.update(status="failed", error_code="assertion_failed")
        elif counts["skipped"]:
            result.update(status="skipped", error_code="required_case_skipped")
        elif counts["collected"] == 0 or counts["passed"] != counts["collected"]:
            result["error_code"] = "empty_or_partial_test_result"
        elif completed.returncode != 0 or counts["exit_code"] != 0:
            result["error_code"] = "test_process_failed"
        else:
            result["status"] = "succeeded"
        result["checks_run"] = counts.get("collected", 0)
    except subprocess.TimeoutExpired:
        result["error_code"] = "case_timeout"
    except (OSError, ValueError, TypeError, AttributeError):
        result["error_code"] = "invalid_test_result"
    result["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
    return result


def fixture_digest(path: Path) -> str:
    content = path.read_bytes()
    content.decode("utf-8")
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def load_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("metric_version") != "task-success-1" or manifest.get("fixture_hash_mode") != "utf8-lf":
        raise ValueError("unsupported_metric_version")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("empty_suite")
    ids = set()
    pattern = r"tests/test_[a-z0-9_]+\.py::test_[a-z0-9_]+(?:\[[a-z0-9_-]+\])?"
    for case in cases:
        if (not re.fullmatch(r"[a-z][a-z0-9_]*", case["id"]) or case["id"] in ids
                or case["suite"] not in ("rules", "legacy")
                or not re.fullmatch(pattern, case["test"])
                or type(case["timeout_seconds"]) is not int or not 1 <= case["timeout_seconds"] <= 120
                or not case["invariants"] or not case["expected"]):
            raise ValueError("invalid_manifest_case")
        ids.add(case["id"])
    return manifest


def rule_coverage() -> dict:
    from app.story_schema import Story
    from app.story_validation import check_reachability
    definition = Story.model_validate(json.loads(
        (BACKEND / "tests" / "fixtures" / "mist_harbor_investigation.json").read_text(encoding="utf-8")))
    proof = check_reachability(definition)
    return {
        "reachability_status": proof.status, "states_checked": proof.states_checked,
        "locations_visited": len(proof.locations), "evidence_discovered": len(proof.evidence),
        "ending_action_counts": {ending: len(actions) for ending, actions in proof.ending_paths.items()},
    }


def run_suite(suite: str, database_url_env: str) -> tuple[dict, Path]:
    manifest = load_manifest()
    cases = [case for case in manifest["cases"] if case["suite"] == suite]
    if not cases:
        raise ValueError("empty_suite")
    run_id = uuid4().hex
    output = ROOT / "runtime" / "evals" / run_id
    output.mkdir(parents=True)
    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    environment.pop("MIGRATION_DATABASE_URL", None)
    error = None
    if suite == "legacy":
        try:
            url = validate_database_url(os.environ.get(database_url_env, ""))
            safe_value = url.render_as_string(hide_password=False)
            environment["DATABASE_URL"] = safe_value
            environment["MIGRATION_DATABASE_URL"] = safe_value
        except ValueError as exc:
            error = str(exc)
    fixture_hashes = {}
    fixture_raw_hashes = {}
    for relative, expected in manifest["fixture_hashes"].items():
        target = (ROOT / relative).resolve()
        if not target.is_relative_to(ROOT.resolve()):
            raise ValueError("invalid_fixture_path")
        digest = fixture_digest(target)
        fixture_raw_hashes[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        fixture_hashes[relative] = digest
        if digest != expected:
            error = "fixture_hash_mismatch"
    started = time.monotonic()
    if error:
        results = [{"id": case["id"], "status": "error", "error_code": error, "duration_ms": 0} for case in cases]
    else:
        results = [execute_case(case, output, environment) for case in cases]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False)
    report = {
        "git_dirty": bool(dirty.stdout.strip()),        "metric_version": manifest["metric_version"], "run_id": run_id, "suite": suite,
        "timestamp": datetime.now(timezone.utc).isoformat(), "git_commit": commit.stdout.strip(),
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "fixture_hashes": fixture_hashes, "fixture_hash_mode": "utf8-lf", "fixture_raw_sha256": fixture_raw_hashes, "story_version": manifest["versions"][suite]["story"],
        "engine_version": manifest["versions"][suite]["engine"], "model_version": None, "prompt_version": None,
        "measurement": "deterministic_rules" if suite == "rules" else "legacy_saved_node_compatibility",
        "provider_calls": 0,
        "coverage": rule_coverage() if suite == "rules" and error is None else None,
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "summary": summarize(results), "cases": results,
    }
    path = output / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("rules", "legacy"), required=True)
    parser.add_argument("--database-url-env", default="MIGRATION_DATABASE_URL")
    args = parser.parse_args(argv)
    try:
        report, path = run_suite(args.suite, args.database_url_env)
    except (ValueError, KeyError, OSError, TypeError, json.JSONDecodeError):
        print("stage1 evaluation: invalid manifest or unavailable fixture")
        return 2
    print(json.dumps({"suite": args.suite, **report["summary"], "report": str(path)}, ensure_ascii=False))
    return 0 if report["summary"]["succeeded"] == report["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
