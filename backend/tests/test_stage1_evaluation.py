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
    for fragment, expected, exit_code in [
        ('<testcase><skipped/></testcase>', "skipped", 0),
        ('<testcase><failure message="secret material"/></testcase>', "failed", 1),
        ('<testcase><error message="secret material"/></testcase>', "error", 2),
        ('<testcase/>', "succeeded", 0),
    ]:
        def run(command, **kwargs):
            report = Path(next(value.split("=", 1)[1] for value in command if value.startswith("--junitxml=")))
            report.write_text("<testsuites><testsuite>" + fragment + "</testsuite></testsuites>", encoding="utf-8")
            return SimpleNamespace(returncode=exit_code)
        monkeypatch.setattr(runner.subprocess, "run", run)
        result = runner.execute_case({"id": "fixed_case", "test": "tests/test_stage1.py::test_replay_reads_saved_bytes_without_generating",
                                      "timeout_seconds": 2}, tmp_path, {})
        assert result["status"] == expected
        assert "secret material" not in str(result)


def test_malformed_or_absent_result_cannot_count_as_success(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    result = runner.execute_case({"id": "empty_result", "test": "tests/test_stage1.py::test_replay_reads_saved_bytes_without_generating",
                                  "timeout_seconds": 2}, tmp_path, {})
    assert result["status"] == "error"
