from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tga_web.domain.models import AnalysisResult
from tga_web.repositories.run_repository import RunRepository
from tga_web.services.url_normalization import UrlNormalizer


@dataclass
class AnalysisService:
    """
    Service layer: orchestrates EXE execution + output discovery.
    Keeps controllers/routes thin.
    """
    exe_path: Path
    timeout_seconds: int
    url_normalizer: UrlNormalizer
    run_repo: RunRepository

    def run(
        self,
        competitor_raw: str,
        baseline_raw: str,
        file_raw: str,
        *,
        extra_instructions: str = "",
        instruction_preset: str = "",
    ) -> AnalysisResult:
        competitor = self.url_normalizer.normalize(competitor_raw)
        baseline = self.url_normalizer.normalize(baseline_raw) if (baseline_raw or "").strip() else ""

        if not competitor:
            raise ValueError("Competitor is required.")

        # Base command
        cmd = [str(self.exe_path), "--competitor", competitor, "--baseline", baseline]

        if (file_raw or "").strip():
            cmd += ["--file", file_raw.strip()]

        # NEW: pass prompt controls to the EXE (only if provided)
        # Your EXE must support these flags; if it doesn't yet, this service will auto-retry without them.
        extra_instructions = (extra_instructions or "").strip()
        instruction_preset = (instruction_preset or "").strip()

        if instruction_preset:
            cmd += ["--instruction-preset", instruction_preset]
        if extra_instructions:
            cmd += ["--extra-instructions", extra_instructions]

        def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=str(self.exe_path.parent),
                timeout=self.timeout_seconds,
            )

        started = datetime.now()

        try:
            proc = _run_command(cmd)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Execution timed out.") from e
        except Exception as e:
            raise RuntimeError(f"Failed to execute: {e}") from e

        # If the EXE hasn't been updated to accept the new flags yet, retry without them
        # (prevents breaking the web UI while you roll out EXE changes).
        stderr_text = (proc.stderr or "")
        unrecognized = (
            "unrecognized arguments" in stderr_text.lower()
            or "unknown option" in stderr_text.lower()
            or "unrecognized option" in stderr_text.lower()
        )
        if proc.returncode != 0 and unrecognized and (extra_instructions or instruction_preset):
            fallback_cmd = [str(self.exe_path), "--competitor", competitor, "--baseline", baseline]
            if (file_raw or "").strip():
                fallback_cmd += ["--file", file_raw.strip()]

            # Re-run without new flags
            started = datetime.now()
            try:
                proc = _run_command(fallback_cmd)
            except subprocess.TimeoutExpired as e:
                raise RuntimeError("Execution timed out.") from e
            except Exception as e:
                raise RuntimeError(f"Failed to execute: {e}") from e

        finished = datetime.now()
        duration_seconds = int((finished - started).total_seconds())
        generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
        run_id = finished.strftime("%Y%m%d_%H%M%S")

        run_dir = self.run_repo.find_newest_run_dir()
        outputs = self.run_repo.pick_outputs(run_dir) if run_dir else None

        stdout_tail = "\n".join((proc.stdout or "").splitlines()[-60:])
        stderr_tail = "\n".join((proc.stderr or "").splitlines()[-60:])

        status = "ok" if proc.returncode == 0 else "failed"

        return AnalysisResult(
            status=status,
            competitor=competitor,
            baseline=baseline,
            generated_at=generated_at,
            duration_seconds=duration_seconds,
            exit_code=proc.returncode,
            run_id=run_id,
            run_dir=str(run_dir) if run_dir else "",
            outputs=outputs,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )






# from __future__ import annotations
#
# import subprocess
# from dataclasses import dataclass
# from datetime import datetime
# from pathlib import Path
#
# from tga_web.domain.models import AnalysisResult
# from tga_web.repositories.run_repository import RunRepository
# from tga_web.services.url_normalization import UrlNormalizer
#
#
# @dataclass
# class AnalysisService:
#     """
#     Service layer: orchestrates EXE execution + output discovery.
#     Keeps controllers/routes thin.
#     """
#     exe_path: Path
#     timeout_seconds: int
#     url_normalizer: UrlNormalizer
#     run_repo: RunRepository
#
#     def run(self, competitor_raw: str, baseline_raw: str, file_raw: str) -> AnalysisResult:
#         competitor = self.url_normalizer.normalize(competitor_raw)
#         baseline = self.url_normalizer.normalize(baseline_raw) if (baseline_raw or "").strip() else ""
#
#         if not competitor:
#             raise ValueError("Competitor is required.")
#
#         cmd = [str(self.exe_path), "--competitor", competitor, "--baseline", baseline]
#         if (file_raw or "").strip():
#             cmd += ["--file", file_raw.strip()]
#
#         started = datetime.now()
#         try:
#             proc = subprocess.run(
#                 cmd,
#                 capture_output=True,
#                 text=True,
#                 cwd=str(self.exe_path.parent),
#                 timeout=self.timeout_seconds,
#             )
#         except subprocess.TimeoutExpired as e:
#             raise RuntimeError("Execution timed out.") from e
#         except Exception as e:
#             raise RuntimeError(f"Failed to execute: {e}") from e
#
#         finished = datetime.now()
#         duration_seconds = int((finished - started).total_seconds())
#         generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
#         run_id = finished.strftime("%Y%m%d_%H%M%S")
#
#         run_dir = self.run_repo.find_newest_run_dir()
#         outputs = self.run_repo.pick_outputs(run_dir) if run_dir else None
#
#         stdout_tail = "\n".join((proc.stdout or "").splitlines()[-60:])
#         stderr_tail = "\n".join((proc.stderr or "").splitlines()[-60:])
#
#         status = "ok" if proc.returncode == 0 else "failed"
#
#         return AnalysisResult(
#             status=status,
#             competitor=competitor,
#             baseline=baseline,
#             generated_at=generated_at,
#             duration_seconds=duration_seconds,
#             exit_code=proc.returncode,
#             run_id=run_id,
#             run_dir=str(run_dir) if run_dir else "",
#             outputs=outputs,
#             stdout_tail=stdout_tail,
#             stderr_tail=stderr_tail,
#         )
