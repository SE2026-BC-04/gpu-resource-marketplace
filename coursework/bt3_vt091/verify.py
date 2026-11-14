"""Reproducible coursework experiments; run using backend's Python environment."""

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
GUARD = '''                if revision < current.revision:
                    raise StaleDraft("a newer draft is already saved")
'''
BLOCK = '''            current = self._rows.get((owner, listing))
            if current is not None:
''' + GUARD + '''                if revision == current.revision:
                    if candidate != current:
                        raise RevisionConflict("same revision contains different fields")
                    return current
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata():
    return {
        "timestamp": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).isoformat(),
        "python": sys.version, "platform": platform.platform(), "logical_cpus": os.cpu_count(),
        "packages": {p: importlib.metadata.version(p) for p in ["pytest", "fastapi", "httpx"]},
        "baseline": "bee832eaf5463df20f6c6815174322871eb6685a",
        "source_sha256": {name: digest(ROOT / name) for name in ["drafts.py", "harness_api.py", "load.py", "verify.py", "tests/test_drafts.py", "tests/test_api.py", "PLAN.md"]},
    }


def run_test(directory, selection=None):
    command = [sys.executable, "-X", "utf8", "-m", "pytest", "-q"] + (selection or ["tests"])
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=60)
    return {"command": command, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def write(name, result):
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def temporary_variant(kind):
    """Temporary Git branch contains the mutation, never the submission source."""
    original = (ROOT / "drafts.py").read_text(encoding="utf-8")
    marker = GUARD if kind == "mutation" else BLOCK
    assert original.count(marker) == 1
    replacement = "" if kind == "mutation" else "            # Test-first scaffold: last arrival wins; patched after the RED run.\n"
    altered = original.replace(marker, replacement)
    with tempfile.TemporaryDirectory(prefix="bt3-vt091-experiment-") as temporary:
        target = Path(temporary)
        for name in ["drafts.py", "harness_api.py", "pytest.ini"]:
            shutil.copy2(ROOT / name, target / name)
        shutil.copytree(ROOT / "tests", target / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        def git(*args):
            return subprocess.run(["git", "-c", "user.name=VT-091 experiment", "-c", "user.email=vt091@example.invalid", *args], cwd=target, check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q")
        git("add", "drafts.py", "harness_api.py", "pytest.ini", "tests")
        git("commit", "-qm", "test(vt091): snapshot accepted harness")
        git("switch", "-qc", "mutation/remove-stale-validation" if kind == "mutation" else "experiment/red-scaffold")
        (target / "drafts.py").write_text(altered, encoding="utf-8", newline="\n")
        git("add", "drafts.py")
        git("commit", "-qm", "test(vt091): remove validation for temporary experiment")
        patch = git("show", "--format=", "--", "drafts.py")
        result = run_test(target, ["tests/test_drafts.py::test_vt03_stale_save_cannot_replace_newer"])
        detected = result["exit_code"] == 1 and "DID NOT RAISE" in result["stdout"] and "StaleDraft" in result["stdout"]
        result.update({"temporary_branch": git("branch", "--show-current"), "temporary_commit": git("rev-parse", "HEAD"), "variant_sha256": digest(target / "drafts.py"), "expected_failure_observed": detected, "metadata": metadata()})
        (EVIDENCE / ("03_mutation.patch" if kind == "mutation" else "01_red_scaffold.patch")).write_text(patch + "\n", encoding="utf-8")
    assert (ROOT / "drafts.py").read_text(encoding="utf-8") == original
    write("03_mutation.json" if kind == "mutation" else "01_red_reproduced.json", result)
    print(json.dumps({"experiment": kind, "expected_failure_observed": detected, "source_unchanged": True}))
    return 0 if detected else 1


def repeated():
    results = []
    selections = ["tests/test_drafts.py::test_vt04_delayed_old_request_finishes_after_new_request", "tests/test_drafts.py::test_vt05_all_arrival_orders_preserve_maximum_revision", "tests/test_drafts.py::test_vt10_storage_failure_keeps_previous_draft_and_next_edit_recovers", "tests/test_api.py::test_vt16_api_two_overlapping_requests_arrive_inverted"]
    for repeat in range(10):
        selected = selections if repeat % 2 == 0 else list(reversed(selections))
        result = run_test(ROOT, selected)
        results.append({"repeat": repeat + 1, **result})
    passed = all(r["exit_code"] == 0 for r in results)
    write("05_repeat.json", {"metadata": metadata(), "runs": results, "pass": passed, "scope": "90 case executions; deterministic Event ordering, fresh process/store; alternating selection order"})
    print(json.dumps({"repeat_runs": 10, "pass": passed}))
    return 0 if passed else 1


def line_coverage():
    import trace
    import pytest
    # Ignore external libraries, not the coursework files imported by pytest.
    tracer = trace.Trace(count=True, trace=False, ignoredirs=[sys.base_prefix, str(Path(pytest.__file__).parents[1])])
    code = tracer.runfunc(pytest.main, ["-q", str(ROOT / "tests")])
    counts = tracer.results().counts
    report = {}
    for name in ["drafts.py", "harness_api.py"]:
        path = str(ROOT / name)
        # Python 3.12's synthetic RESUME bytecode can use line 0; it is not source.
        executable = {line for line in trace._find_executable_linenos(path) if line > 0}
        hit = {lineno for filename, lineno in counts if os.path.normcase(filename) == os.path.normcase(path) and counts[(filename, lineno)] > 0}
        missing = sorted(set(executable) - hit)
        report[name] = {"executable_lines": len(executable), "hit_lines": len(set(executable) & hit), "missing_lines": missing, "line_percent": round(100 * len(set(executable) & hit) / len(executable), 2)}
    write("07_line_coverage.json", {"metadata": metadata(), "tool": "Python 3.12 stdlib trace executable-line analysis", "test_exit_code": int(code), "files": report, "branch_coverage": "NOT_RUN: stdlib trace does not measure branch coverage; no coverage plugin installed", "limitation": "line execution is not assertion quality; use mutation and AC/risk traceability"})
    print(json.dumps(report, indent=2))
    return int(code)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["red", "green", "mutation", "load", "repeat", "coverage"])
    args = parser.parse_args()
    EVIDENCE.mkdir(exist_ok=True)
    if args.mode in {"red", "mutation"}:
        return temporary_variant(args.mode)
    if args.mode == "repeat":
        return repeated()
    if args.mode == "coverage":
        return line_coverage()
    if args.mode == "green":
        result = run_test(ROOT)
        write("02_green.json", {"metadata": metadata(), **result})
        print(result["stdout"])
        return result["exit_code"]
    started = time.perf_counter()
    result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "load.py")], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
    output = json.loads(result.stdout)
    output["metadata"] = metadata()
    output["exit_code"] = result.returncode
    output["experiment_seconds"] = time.perf_counter() - started
    write("04_load.json", output)
    print(json.dumps([{k: r[k] for k in ["profile", "run", "completed", "p95_ms", "unexpected_errors", "invariant_pass", "pass"]} for r in output["runs"]], indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
