from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytest

from tga_web.domain.models import RunOutputs
from tga_web.services.analysis_service import AnalysisService
from tga_web.services.url_normalization import GuessComUrlNormalizer


# -----------------------------
# Test doubles
# -----------------------------
@dataclass
class FakeCompletedProcess:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class FakeRunRepository:
    def __init__(self, run_dir: Optional[Path], outputs: Optional[RunOutputs]):
        self._run_dir = run_dir
        self._outputs = outputs

    def find_newest_run_dir(self) -> Optional[Path]:
        return self._run_dir

    def pick_outputs(self, run_dir: Path) -> RunOutputs:
        # ignore run_dir; deterministic for tests
        return self._outputs or RunOutputs(html=None, docx=None, pptx=None, md=None)


# -----------------------------
# Helpers
# -----------------------------
def make_service(tmp_path: Path, run_dir: Optional[Path], outputs: Optional[RunOutputs]) -> AnalysisService:
    exe_path = tmp_path / "fake.exe"
    exe_path.write_text("not really an exe")  # just needs to exist as a Path
