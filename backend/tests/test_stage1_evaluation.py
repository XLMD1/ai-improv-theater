import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

path = Path(__file__).resolve().parents[2] / "evals" / "run_stage1.py"
spec = importlib.util.spec_from_file_location("stage1_eval", path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_fixed_denominator_includes_failure_error_and_skip():
    summary = runner.summarize([
        {"status": "succeeded"}, {"status": "failed"}, {"status": "error"}, {"status": "skipped"}
    ])
    assert summary == {"total": 4, "succeeded": 1, "failed": 1, "error": 1, "skipped": 1,
                       "task_success_rate": .25}
    with pytest.raises(ValueError, match="empty_suite"):
        runner.summarize([])


@pytest.mark.parametrize("url", [
    "", "invalid", "sqlite:///story_test", "postgresql+psycopg://user:password@localhost/theater",
])
def test_legacy_refuses_missing_or_unsafe_database_before_start(url):
    with pytest.raises(ValueError, match="dedicated_postgresql_test_database_required"):
        runner.validate_database_url(url)


def test_subprocess_timeout_is_error_and_keeps_denominator(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("pytest", 1)
    monkeypatch.setattr(runner.subprocess, "run", timeout)
    case = {"id": "timeout_case", "test": "tests/test_investigation_rules.py::test_same_location_repeated_and_invalid_actions_preserve_parent",
            "timeout_seconds": 1}
    result = runner.execute_case(case, tmp_path, {})
    assert result["status"] == "error"
    assert result["error_code"] == "case_timeout"
    assert runner.summarize([result])["task_success_rate"] == 0


def test_skip_and_assertion_failure_cannot_count_as_success(monkeypatch, tmp_path):
    import json
    for status, expected, exit_code in [
        ("skipped", "skipped", 0), ("failed", "failed", 1),
        ("error", "error", 2), ("passed", "succeeded", 0),
    ]:
        def run(command, **kwargs):
            report = Path(next(value.split("=", 1)[1] for value in command if value.startswith("--stage1-result=")))
            counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0,
                      "collected": 1, "deselected": 0, "exit_code": exit_code}
            counts[status] = 1
            report.write_text(json.dumps(counts), encoding="utf-8")
            return SimpleNamespace(returncode=exit_code)
        monkeypatch.setattr(runner.subprocess, "run", run)
        result = runner.execute_case({"id": "fixed_case", "test": "tests/test_stage1.py::test_replay_reads_saved_bytes_without_generating",
                                      "timeout_seconds": 2}, tmp_path, {})
        assert result["status"] == expected


def test_malformed_or_absent_result_cannot_count_as_success(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    result = runner.execute_case({"id": "empty_result", "test": "tests/test_stage1.py::test_replay_reads_saved_bytes_without_generating",
                                  "timeout_seconds": 2}, tmp_path, {})
    assert result["status"] == "error"

def test_report_coverage_measures_witness_actions_and_locations():
    coverage = runner.rule_coverage()
    assert coverage["reachability_status"] == "passed"
    assert coverage["states_checked"] == 70
    assert coverage["locations_visited"] == 5
    assert coverage["evidence_discovered"] == 12
    assert coverage["ending_action_counts"] == {
        "publish_truth": 21, "guard_together": 21, "sink_secret": 21}

def test_inherited_pytest_selector_cannot_remove_required_checks(tmp_path):
    import json
    import os
    environment = dict(os.environ)
    environment["PYTEST_ADDOPTS"] = "-k engine_version"
    case = {"id": "all_state_checks", "test": "tests/test_investigation_rules.py::test_forged_state_is_rejected",
            "timeout_seconds": 30}
    result = runner.execute_case(case, tmp_path, environment)
    assert result["status"] == "succeeded"
    assert result["checks_run"] == 13
    saved = json.loads((tmp_path / "all_state_checks.json").read_text(encoding="utf-8"))
    assert saved["passed"] == 13
    assert saved["deselected"] == 0
    assert environment["PYTEST_ADDOPTS"] == "-k engine_version"


def test_saved_artifacts_never_include_raw_failure_or_output(tmp_path):
    secret = "fake_session_token_do_not_persist"
    source = tmp_path / "test_private_failure.py"
    source.write_text("def test_private():\n    print('" + secret + "')\n    assert False, '" + secret + "'\n",
                      encoding="utf-8")
    output = tmp_path / "results"
    output.mkdir()
    import os
    result = runner.execute_case(
        {"id": "private_failure", "test": str(source) + "::test_private", "timeout_seconds": 30},
        output, dict(os.environ))
    assert result["status"] == "failed"
    assert secret not in str(result)
    assert all(secret not in artifact.read_text(encoding="utf-8") for artifact in output.iterdir())
