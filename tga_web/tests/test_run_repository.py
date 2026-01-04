from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tga_web.repositories.run_repository import RunRepository


def _make_run_dir(base: Path, name: str, mtime: float) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    # Set directory mtime deterministically
    os.utime(d, (mtime, mtime))
    return d


def _touch_file(path: Path, mtime: float) -> None:
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_find_newest_run_dir_in_reports_base_when_only_reports_has_runs(tmp_path: Path):
    reports_base = tmp_path / "reports"
    exe_dir = tmp_path / "exe_dir"
    reports_base.mkdir()
    exe_dir.mkdir()

    t0 = time.time()

    _make_run_dir(reports_base, "comparison_report_older", t0 - 100)
    newest = _make_run_dir(reports_base, "comparison_report_newest", t0 - 10)

    repo = RunRepository(reports_base=reports_base, exe_dir=exe_dir)

    got = repo.find_newest_run_dir()
    assert got is not None
    assert got.name == newest.name


def test_find_newest_run_dir_in_exe_dir_when_only_exe_has_runs(tmp_path: Path):
    reports_base = tmp_path / "reports"
    exe_dir = tmp_path / "exe_dir"
    reports_base.mkdir()
    exe_dir.mkdir()

    t0 = time.time()

    newest = _make_run_dir(exe_dir, "comparison_report_newest", t0 - 5)
    _make_run_dir(exe_dir, "comparison_report_older", t0 - 50)

    repo = RunRepository(reports_base=reports_base, exe_dir=exe_dir)

    got = repo.find_newest_run_dir()
    assert got is not None
    assert got.name == newest.name


def test_find_newest_prefers_more_recent_between_reports_and_exe(tmp_path: Path):
    reports_base = tmp_path / "reports"
    exe_dir = tmp_path / "exe_dir"
    reports_base.mkdir()
    exe_dir.mkdir()

    t0 = time.time()

    # reports has a run, but exe_dir has a newer run -> should pick exe_dir
    _make_run_dir(reports_base, "comparison_report_reports", t0 - 20)
    newest = _make_run_dir(exe_dir, "comparison_report_exe", t0 - 1)

    repo = RunRepository(reports_base=reports_base, exe_dir=exe_dir)

    got = repo.find_newest_run_dir()
    assert got is not None
    assert got.name == newest.name


def test_find_newest_returns_none_when_no_matching_dirs(tmp_path: Path):
    reports_base = tmp_path / "reports"
    exe_dir = tmp_path / "exe_dir"
    reports_base.mkdir()
    exe_dir.mkdir()

    # Non-matching directories should be ignored
    (reports_base / "not_a_report").mkdir()
    (exe_dir / "something_else").mkdir()

    repo = RunRepository(reports_base=reports_base, exe_dir=exe_dir)

    assert repo.find_newest_run_dir() is None


def test_pick_outputs_finds_expected_files(tmp_path: Path):
    reports_base = tmp_path / "reports"
    exe_dir = tmp_path / "exe_dir"
    reports_base.mkdir()
    exe_dir.mkdir()

    run_dir = _make_run_dir(reports_base, "comparison_report_20250101_010101", time.time())

    # Create one of each output type
    t0 = time.time()
    html = run_dir / "report.html"
    docx = run_dir / "report.docx"
    pptx = run_dir / "report.pptx"
    md = run_dir / "report.md"

    _touch_file(html, t0)
    _touch_file(docx, t0)
    _touch_file(pptx, t0)
    _touch_file(md, t0)

    repo = RunRepository(reports_base=reports_base, exe_dir=exe_dir)

    outputs = repo.pick_outputs(run_dir)

    assert outputs.html == html
    assert outputs.docx == docx
    assert outputs.pptx == pptx
    assert outputs.md == md


def test_pick_outputs_returns_none_when_missing(tmp_path: Path):
    reports_base = tmp_path / "reports"
    exe_dir = tmp_path / "exe_dir"
    reports_base.mkdir()
    exe_dir.mkdir()

    run_dir = _make_run_dir(reports_base, "comparison_report_20250101_010101", time.time())
    # Only create html
    html = run_dir / "only.html"
    _touch_file(html, time.time())

    repo = RunRepository(reports_base=reports_base, exe_dir=exe_dir)

    outputs = repo.pick_outputs(run_dir)

    assert outputs.html == html
    assert outputs.docx is None
    assert outputs.pptx is None
    assert outputs.md is None
