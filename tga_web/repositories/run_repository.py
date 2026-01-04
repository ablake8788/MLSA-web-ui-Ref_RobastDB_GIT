from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tga_web.domain.models import RunOutputs


def _newest_run_dir_in(base: Path) -> Optional[Path]:
    if not base.exists():
        return None
    candidates = [p for p in base.iterdir() if p.is_dir() and p.name.startswith("comparison_report_")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


@dataclass
class RunRepository:
    """
    Repository pattern: encapsulates locating run folders and enumerating outputs.
    """
    reports_base: Path
    exe_dir: Path

    def find_newest_run_dir(self) -> Optional[Path]:
        a = _newest_run_dir_in(self.reports_base)
        b = _newest_run_dir_in(self.exe_dir)
        if a and b:
            return a if a.stat().st_mtime >= b.stat().st_mtime else b
        return a or b

    def pick_outputs(self, run_dir: Path) -> RunOutputs:
        return RunOutputs(
            html=next(run_dir.glob("*.html"), None),
            docx=next(run_dir.glob("*.docx"), None),
            pptx=next(run_dir.glob("*.pptx"), None),
            md=next(run_dir.glob("*.md"), None),
        )
