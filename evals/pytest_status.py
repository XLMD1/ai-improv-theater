"""Pytest status projection: never persist diagnostics, node IDs or captured output."""
import json
from pathlib import Path

_outcomes = {}
_collection_errors = 0
_collection_skips = 0
_deselected = 0
_internal_errors = 0
_priority = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}


def pytest_addoption(parser):
    parser.addoption("--stage1-result", action="store", default=None)


def pytest_runtest_logreport(report):
    if report.failed:
        status = "failed" if report.when == "call" else "error"
    elif report.skipped:
        status = "skipped"
    elif report.when == "call" and report.passed:
        status = "passed"
    else:
        return
    previous = _outcomes.get(report.nodeid, "passed")
    if _priority[status] >= _priority[previous]:
        _outcomes[report.nodeid] = status


def pytest_collectreport(report):
    global _collection_errors, _collection_skips
    _collection_errors += int(report.failed)
    _collection_skips += int(report.skipped)


def pytest_deselected(items):
    global _deselected
    _deselected += len(items)


def pytest_internalerror(excrepr, excinfo):
    global _internal_errors
    _internal_errors += 1


def pytest_sessionfinish(session, exitstatus):
    target = session.config.getoption("--stage1-result")
    if target is None:
        return
    counts = {status: sum(value == status for value in _outcomes.values()) for status in _priority}
    counts["error"] += _collection_errors + _internal_errors
    counts["skipped"] += _collection_skips
    counts.update(collected=session.testscollected, deselected=_deselected, exit_code=int(exitstatus))
    Path(target).write_text(json.dumps(counts) + "\n", encoding="utf-8")
