######## models.py
########

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

@dataclass(frozen=True)
class RunOutputs:
    html: Optional[Path]
    docx: Optional[Path]
    pptx: Optional[Path]
    md: Optional[Path]


@dataclass(frozen=True)
class AnalysisResult:
    status: str                 # "ok" | "failed"
    competitor: str
    baseline: str
    generated_at: str
    duration_seconds: int
    exit_code: int
    run_id: str
    run_dir: str
    outputs: RunOutputs
    stdout_tail: str
    stderr_tail: str
