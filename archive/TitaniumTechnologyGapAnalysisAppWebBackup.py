import os
import re
import subprocess
from configparser import ConfigParser
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, render_template, request, url_for, send_from_directory, abort


# -----------------------------
# Config loading
# -----------------------------
INI_DEFAULT_NAME = "TitaniumTechnologyGapAnalysisApp.ini"


def load_config() -> ConfigParser:
    """
    Loads TitaniumTechnologyGapAnalysisApp.ini from the same directory as this script
    by default. Allows override via env var APP_INI.
    """
    cfg = ConfigParser()

    ini_path = Path(os.getenv("APP_INI", Path(__file__).with_name(INI_DEFAULT_NAME)))
    read_ok = cfg.read(ini_path)

    if not read_ok:
        raise FileNotFoundError(f"INI file not found or unreadable: {ini_path}")

    return cfg


CFG = load_config()

# -----------------------------
# Config values
# -----------------------------
REPORTS_BASE = Path(CFG.get("paths", "reports_base"))
EXE_PATH = Path(CFG.get("paths", "exe_path"))

TIMEOUT_SECONDS = CFG.getint("execution", "timeout_seconds", fallback=60 * 30)

DEFAULT_SCHEME = CFG.get("url_normalization", "default_scheme", fallback="https").strip() or "https"
GUESS_COM_IF_NO_DOT = CFG.getboolean("url_normalization", "guess_com_if_no_dot", fallback=True)

NO_GUESS_HOSTS = {
    h.strip().lower()
    for h in CFG.get("url_normalization", "no_guess_hosts", fallback="localhost").split(",")
    if h.strip()
}

FLASK_HOST = CFG.get("flask", "host", fallback="127.0.0.1")
FLASK_PORT = CFG.getint("flask", "port", fallback=5000)
FLASK_DEBUG = CFG.getboolean("flask", "debug", fallback=True)

# -----------------------------
# Validation (fail fast)
# -----------------------------
if not EXE_PATH.exists():
    raise FileNotFoundError(f"EXE not found: {EXE_PATH}")

if not REPORTS_BASE.exists():
    # If you want to auto-create, uncomment:
    # REPORTS_BASE.mkdir(parents=True, exist_ok=True)
    raise FileNotFoundError(f"Reports base folder not found: {REPORTS_BASE}")

# -----------------------------
# Flask app
# -----------------------------
app = Flask(__name__)


# -----------------------------
# Input normalization
# -----------------------------
def normalize_url_guess_com(s: str) -> str:
    """
    Accepts:
      - door.com
      - https://door.com
      - door          (guesses .com depending on INI)
      - tektelic.com/path
    Produces:
      - https://door.com
      - https://tektelic.com/path
    """
    s = (s or "").strip()
    if not s:
        return ""

    # Keep if already has scheme
    if re.match(r"^https?://", s, flags=re.IGNORECASE):
        return s

    # Split host/path
    parts = s.split("/", 1)
    host = parts[0].strip()
    rest = ("/" + parts[1]) if len(parts) > 1 else ""

    # Guess .com if no dot (except configured exclusions)
    if GUESS_COM_IF_NO_DOT and "." not in host and host.lower() not in NO_GUESS_HOSTS:
        host = host + ".com"

    return f"{DEFAULT_SCHEME}://" + host + rest


# -----------------------------
# Report folder detection
# -----------------------------
def newest_report_run_dir(reports_base: Path) -> Optional[Path]:
    if not reports_base.exists():
        return None
    dirs = [p for p in reports_base.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def detect_new_run_dir(reports_base: Path, before_dirs: set[str]) -> Optional[Path]:
    """
    Detects a newly-created run directory after the EXE runs.
    Falls back to newest overall if nothing new was created (rare).
    """
    if not reports_base.exists():
        return None

    after_dirs = {p.name for p in reports_base.iterdir() if p.is_dir()}
    created = [reports_base / name for name in (after_dirs - before_dirs)]
    if created:
        return max(created, key=lambda p: p.stat().st_mtime)

    return newest_report_run_dir(reports_base)


# -----------------------------
# Safe serving of generated reports
# -----------------------------
@app.get("/reports/<path:relpath>")
def serve_report(relpath: str):
    """
    Serves generated reports from disk so the browser can load them (iframe / downloads).
    """
    rel = Path(relpath)
    full = (REPORTS_BASE / rel).resolve()
    base = REPORTS_BASE.resolve()

    # Path traversal protection
    if base not in full.parents and full != base:
        abort(403)

    if not full.exists() or not full.is_file():
        abort(404)

    return send_from_directory(full.parent, full.name, as_attachment=False)


# -----------------------------
# Pages
# -----------------------------
@app.get("/")
def index():
    return render_template("index.html")
@app.post("/run")
def run_analysis():
    competitor_raw = request.form.get("competitor", "").strip()
    baseline_raw = request.form.get("baseline", "").strip()   # FIXED
    file_raw = request.form.get("file", "").strip()

    competitor_norm = normalize_url_guess_com(competitor_raw)
    baseline_norm = normalize_url_guess_com(baseline_raw) if baseline_raw else ""

    if not competitor_norm:
        return render_template("index.html", error="Competitor is required."), 400

    # Build command
    cmd = [str(EXE_PATH), "--competitor", competitor_norm]
    if baseline_raw != "":  # user touched the field (including blank)
        # Option A (recommended if you want blank field to DISABLE baseline even if INI has one):
        # Always pass --baseline; empty means disable in your EXE argparse (nargs="?", const="")
        cmd += ["--baseline", baseline_norm]  # baseline_norm may be ""
    # If you want empty field to mean "use INI fallback", then use instead:
    # if baseline_norm:
    #     cmd += ["--baseline", baseline_norm]

    if file_raw:
        cmd += ["--file", file_raw]

    # Track report directories BEFORE run
    before_dirs = set()
    if REPORTS_BASE.exists():
        before_dirs = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}

    started = datetime.now()

    # Debug: confirm what is being executed
    app.logger.info("Running command: %r", cmd)

    # Execute
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(EXE_PATH.parent),
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return render_template("index.html", error="Execution timed out."), 500
    except Exception as e:
        return render_template("index.html", error=f"Failed to execute: {e}"), 500

    finished = datetime.now()
    generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
    duration_seconds = int((finished - started).total_seconds())

    # Detect run dir + generated artifacts
    run_dir = detect_new_run_dir(REPORTS_BASE, before_dirs)

    generated = {"html": None, "docx": None, "pptx": None, "md": None}
    if run_dir and run_dir.exists():
        html = next(run_dir.glob("*.html"), None)
        docx = next(run_dir.glob("*.docx"), None)
        pptx = next(run_dir.glob("*.pptx"), None)
        md = next(run_dir.glob("*.md"), None)

        def to_report_url(p: Optional[Path]) -> Optional[str]:
            if not p:
                return None
            rel = p.relative_to(REPORTS_BASE).as_posix()
            return url_for("serve_report", relpath=rel)

        generated = {
            "html": to_report_url(html),
            "docx": to_report_url(docx),
            "pptx": to_report_url(pptx),
            "md": to_report_url(md),
        }

    stdout_tail = "\n".join((proc.stdout or "").splitlines()[-40:])
    stderr_tail = "\n".join((proc.stderr or "").splitlines()[-40:])

    if proc.returncode != 0:
        return render_template(
            "result.html",
            status="failed",
            competitor=competitor_norm,
            baseline=baseline_norm,
            generated_at=generated_at,
            duration_seconds=duration_seconds,
            exit_code=proc.returncode,
            generated=generated,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        ), 500

    return render_template(
        "result.html",
        status="ok",
        competitor=competitor_norm,
        baseline=baseline_norm,
        generated_at=generated_at,
        duration_seconds=duration_seconds,
        exit_code=0,
        generated=generated,
    )


# @app.post("/run")
# def run_analysis():
#     competitor_raw = request.form.get("competitor", "").strip()
#     # baseline_raw = request.form.get("baseline", "").strip()
#     baseline_raw = request.form.get("baseline", "").strip()
#     file_raw = request.form.get("file", "").strip()
#
#     competitor_norm = normalize_url_guess_com(competitor_raw)
#     baseline_norm = normalize_url_guess_com(baseline_raw) if baseline_raw else ""
#
#     if not competitor_norm:
#         return render_template("index.html", error="Competitor is required."), 400
#
#     # Build command
#     cmd = [str(EXE_PATH), "--competitor", competitor_norm]
#     if baseline_norm:
#         cmd += ["--baseline", baseline_norm]
#     if file_raw:
#         cmd += ["--file", file_raw]
#
#     # Track report directories BEFORE run
#     before_dirs = set()
#     if REPORTS_BASE.exists():
#         before_dirs = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
#
#     started = datetime.now()
#
#     # Execute
#     try:
#         proc = subprocess.run(
#             cmd,
#             capture_output=True,
#             text=True,
#             cwd=str(EXE_PATH.parent),
#             timeout=TIMEOUT_SECONDS,
#         )
#     except subprocess.TimeoutExpired:
#         return render_template("index.html", error="Execution timed out."), 500
#     except Exception as e:
#         return render_template("index.html", error=f"Failed to execute: {e}"), 500
#
#     finished = datetime.now()
#     generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
#     duration_seconds = int((finished - started).total_seconds())
#
#     # Detect run dir + generated artifacts
#     run_dir = detect_new_run_dir(REPORTS_BASE, before_dirs)
#
#     generated = {"html": None, "docx": None, "pptx": None, "md": None}
#     if run_dir and run_dir.exists():
#         html = next(run_dir.glob("*.html"), None)
#         docx = next(run_dir.glob("*.docx"), None)
#         pptx = next(run_dir.glob("*.pptx"), None)
#         md = next(run_dir.glob("*.md"), None)
#
#         def to_report_url(p: Optional[Path]) -> Optional[str]:
#             if not p:
#                 return None
#             rel = p.relative_to(REPORTS_BASE).as_posix()
#             return url_for("serve_report", relpath=rel)
#
#         generated = {
#             "html": to_report_url(html),
#             "docx": to_report_url(docx),
#             "pptx": to_report_url(pptx),
#             "md": to_report_url(md),
#         }
#
#     stdout_tail = "\n".join((proc.stdout or "").splitlines()[-40:])
#     stderr_tail = "\n".join((proc.stderr or "").splitlines()[-40:])
#
#     # FAIL path
#     if proc.returncode != 0:
#         return render_template(
#             "result.html",
#             status="failed",
#             competitor=competitor_norm,
#             baseline=baseline_norm,
#             generated_at=generated_at,
#             duration_seconds=duration_seconds,
#             exit_code=proc.returncode,
#             generated=generated,
#             stdout_tail=stdout_tail,
#             stderr_tail=stderr_tail,
#         ), 500
#
#     # OK path
#     return render_template(
#         "result.html",
#         status="ok",
#         competitor=competitor_norm,
#         baseline=baseline_norm,
#         generated_at=generated_at,
#         duration_seconds=duration_seconds,
#         exit_code=0,
#         generated=generated,
#     )


if __name__ == "__main__":
    # Local dev only
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)



# import re
# import subprocess
# from datetime import datetime
# from pathlib import Path
# from typing import Optional
#
# from flask import Flask, render_template, request, url_for, send_from_directory, abort
#
# app = Flask(__name__)
#
# # MUST match where your EXE writes reports (per your log).
# REPORTS_BASE = Path(
#     r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\reports"
# )
#
# # Path to your EXE
# EXE_PATH = Path(
#     r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\TitaniumTechnologyGapAnalysis.exe"
# )
#
#
# # -----------------------------
# # Input normalization
# # -----------------------------
# def normalize_url_guess_com(s: str) -> str:
#     """
#     Accepts:
#       - door.com
#       - https://door.com
#       - door          (guesses .com)
#       - tektelic.com/path
#     Produces:
#       - https://door.com
#       - https://tektelic.com/path
#     """
#     s = (s or "").strip()
#     if not s:
#         return ""
#
#     # Keep if already has scheme
#     if re.match(r"^https?://", s, flags=re.IGNORECASE):
#         return s
#
#     # Split host/path
#     parts = s.split("/", 1)
#     host = parts[0].strip()
#     rest = ("/" + parts[1]) if len(parts) > 1 else ""
#
#     # Guess .com if no dot (except localhost)
#     if "." not in host and host.lower() not in {"localhost"}:
#         host = host + ".com"
#
#     return "https://" + host + rest
#
#
# # -----------------------------
# # Report folder detection
# # -----------------------------
# def newest_report_run_dir(reports_base: Path) -> Optional[Path]:
#     if not reports_base.exists():
#         return None
#     dirs = [p for p in reports_base.iterdir() if p.is_dir()]
#     if not dirs:
#         return None
#     return max(dirs, key=lambda p: p.stat().st_mtime)
#
#
# def detect_new_run_dir(reports_base: Path, before_dirs: set[str]) -> Optional[Path]:
#     """
#     Detects a newly-created run directory after the EXE runs.
#     Falls back to newest overall if nothing new was created (rare).
#     """
#     if not reports_base.exists():
#         return None
#
#     after_dirs = {p.name for p in reports_base.iterdir() if p.is_dir()}
#     created = [reports_base / name for name in (after_dirs - before_dirs)]
#     if created:
#         return max(created, key=lambda p: p.stat().st_mtime)
#
#     return newest_report_run_dir(reports_base)
#
#
# # -----------------------------
# # Safe serving of generated reports
# # -----------------------------
# @app.get("/reports/<path:relpath>")
# def serve_report(relpath: str):
#     """
#     Serves generated reports from disk so the browser can load them (iframe / downloads).
#     """
#     rel = Path(relpath)
#     full = (REPORTS_BASE / rel).resolve()
#     base = REPORTS_BASE.resolve()
#
#     # Path traversal protection
#     if base not in full.parents and full != base:
#         abort(403)
#
#     if not full.exists() or not full.is_file():
#         abort(404)
#
#     # For HTML preview: as_attachment=False
#     return send_from_directory(full.parent, full.name, as_attachment=False)
#
#
# # -----------------------------
# # Pages
# # -----------------------------
# @app.get("/")
# def index():
#     return render_template("index.html")
#
#
# @app.post("/run")
# def run_analysis():
#     competitor_raw = request.form.get("competitor", "").strip()
#     baseline_raw = request.form.get("baseline", "").strip()
#     file_raw = request.form.get("file", "").strip()
#
#     competitor_norm = normalize_url_guess_com(competitor_raw)
#     baseline_norm = normalize_url_guess_com(baseline_raw) if baseline_raw else ""
#
#     if not competitor_norm:
#         return render_template("index.html", error="Competitor is required."), 400
#
#     # Build command
#     cmd = [str(EXE_PATH), "--competitor", competitor_norm]
#     if baseline_norm:
#         cmd += ["--baseline", baseline_norm]
#     if file_raw:
#         cmd += ["--file", file_raw]
#
#     # Validate EXE path early
#     if not EXE_PATH.exists():
#         return render_template("index.html", error=f"EXE not found: {EXE_PATH}"), 500
#
#     # Track report directories BEFORE run
#     before_dirs = set()
#     if REPORTS_BASE.exists():
#         before_dirs = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
#
#     started = datetime.now()
#
#     # Execute
#     try:
#         proc = subprocess.run(
#             cmd,
#             capture_output=True,
#             text=True,
#             cwd=str(EXE_PATH.parent),
#             timeout=60 * 30,  # 30 minutes
#         )
#     except subprocess.TimeoutExpired:
#         return render_template("index.html", error="Execution timed out."), 500
#     except Exception as e:
#         return render_template("index.html", error=f"Failed to execute: {e}"), 500
#
#     finished = datetime.now()
#     generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
#     duration_seconds = int((finished - started).total_seconds())
#
#     # Detect run dir + generated artifacts
#     run_dir = detect_new_run_dir(REPORTS_BASE, before_dirs)
#
#     generated = {"html": None, "docx": None, "pptx": None, "md": None}
#     if run_dir and run_dir.exists():
#         html = next(run_dir.glob("*.html"), None)
#         docx = next(run_dir.glob("*.docx"), None)
#         pptx = next(run_dir.glob("*.pptx"), None)
#         md = next(run_dir.glob("*.md"), None)
#
#         def to_report_url(p: Optional[Path]) -> Optional[str]:
#             if not p:
#                 return None
#             rel = p.relative_to(REPORTS_BASE).as_posix()
#             return url_for("serve_report", relpath=rel)
#
#         generated = {
#             "html": to_report_url(html),
#             "docx": to_report_url(docx),
#             "pptx": to_report_url(pptx),
#             "md": to_report_url(md),
#         }
#
#     # Diagnostics tails (render only if failed; your template should hide on success)
#     stdout_tail = "\n".join((proc.stdout or "").splitlines()[-40:])
#     stderr_tail = "\n".join((proc.stderr or "").splitlines()[-40:])
#
#     # FAIL path
#     if proc.returncode != 0:
#         return render_template(
#             "result.html",
#             status="failed",
#             competitor=competitor_norm,
#             baseline=baseline_norm,
#             generated_at=generated_at,
#             duration_seconds=duration_seconds,
#             exit_code=proc.returncode,
#             generated=generated,
#             stdout_tail=stdout_tail,
#             stderr_tail=stderr_tail,
#         ), 500
#
#     # OK path
#     return render_template(
#         "result.html",
#         status="ok",
#         competitor=competitor_norm,
#         baseline=baseline_norm,
#         generated_at=generated_at,
#         duration_seconds=duration_seconds,
#         exit_code=0,
#         generated=generated,
#     )
#
#
# if __name__ == "__main__":
#     # Local dev only
#     app.run(host="127.0.0.1", port=5000, debug=True)
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
# # import os
# # import re
# # import subprocess
# # from datetime import datetime
# # from pathlib import Path
# #
# # from flask import Flask, render_template, request, url_for, send_from_directory, abort
# #
# # app = Flask(__name__)
# #
# # # MUST match where your EXE writes reports (per your log).
# # REPORTS_BASE = Path(
# #     r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\reports"
# # )
# #
# # # Path to your EXE
# # EXE_PATH = Path(
# #     r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\TitaniumTechnologyGapAnalysis.exe"
# # )
# #
# #
# # def normalize_url_guess_com(s: str) -> str:
# #     """
# #     Accepts:
# #       - door.com
# #       - https://door.com
# #       - door          (we will guess .com here, per your latest script behavior)
# #     Produces:
# #       - https://door.com
# #     """
# #     s = (s or "").strip()
# #     if not s:
# #         return ""
# #
# #     if re.match(r"^https?://", s, flags=re.IGNORECASE):
# #         return s
# #
# #     parts = s.split("/", 1)
# #     host = parts[0].strip()
# #     rest = ("/" + parts[1]) if len(parts) > 1 else ""
# #
# #     if "." not in host and host.lower() not in {"localhost"}:
# #         host = host + ".com"
# #
# #     return "https://" + host + rest
# #
# #
# # def newest_report_run_dir(reports_base: Path) -> Path | None:
# #     if not reports_base.exists():
# #         return None
# #     dirs = [p for p in reports_base.iterdir() if p.is_dir()]
# #     if not dirs:
# #         return None
# #     return max(dirs, key=lambda p: p.stat().st_mtime)
# #
# #
# # @app.get("/reports/<path:relpath>")
# # def serve_report(relpath: str):
# #     """
# #     Serves generated reports from disk so the browser can load them (iframe / downloads).
# #     """
# #     rel = Path(relpath)
# #     full = (REPORTS_BASE / rel).resolve()
# #     base = REPORTS_BASE.resolve()
# #
# #     # Path traversal protection
# #     if base not in full.parents and full != base:
# #         abort(403)
# #
# #     if not full.exists() or not full.is_file():
# #         abort(404)
# #
# #     # For HTML preview: as_attachment=False
# #     return send_from_directory(full.parent, full.name, as_attachment=False)
# #
# #
# # @app.get("/")
# # def index():
# #     return render_template("index.html")
# #
# #
# # @app.post("/run")
# # def run_analysis():
# #     competitor_raw = request.form.get("competitor", "").strip()
# #     baseline_raw = request.form.get("baseline", "").strip()
# #     file_raw = request.form.get("file", "").strip()
# #
# #     # Normalize inputs
# #     competitor_norm = normalize_url_guess_com(competitor_raw)
# #     baseline_norm = normalize_url_guess_com(baseline_raw) if baseline_raw else ""
# #
# #     if not competitor_norm:
# #         return render_template("index.html", error="Competitor is required."), 400
# #
# #     # Build command
# #     cmd = [str(EXE_PATH), "--competitor", competitor_norm]
# #     if baseline_norm:
# #         cmd += ["--baseline", baseline_norm]
# #     if file_raw:
# #         cmd += ["--file", file_raw]
# #
# #     # Track what folder existed BEFORE run, so we can reliably detect the new run folder
# #     before = set()
# #     if REPORTS_BASE.exists():
# #         before = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
# #
# #     # Execute
# #     started = datetime.now()
# #     try:
# #         proc = subprocess.run(
# #             cmd,
# #             capture_output=True,
# #             text=True,
# #             cwd=str(EXE_PATH.parent),
# #             timeout=60 * 30,  # 30 minutes safety
# #         )
# #     except FileNotFoundError:
# #         return render_template("index.html", error=f"EXE not found: {EXE_PATH}"), 500
# #     except subprocess.TimeoutExpired:
# #         return render_template("index.html", error="Execution timed out."), 500
# #     except Exception as e:
# #         return render_template("index.html", error=f"Failed to execute: {e}"), 500
# #
# #     finished = datetime.now()
# #     generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
# #
# #     # Detect the new report folder
# #     run_dir = None
# #     if REPORTS_BASE.exists():
# #         after = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
# #         created = sorted(list(after - before))
# #         if created:
# #             # pick newest among newly created
# #             candidates = [REPORTS_BASE / name for name in created]
# #             run_dir = max(candidates, key=lambda p: p.stat().st_mtime)
# #         else:
# #             # fallback: newest overall
# #             run_dir = newest_report_run_dir(REPORTS_BASE)
# #
# #     generated = {"html": None, "docx": None, "pptx": None, "md": None}
# #     report_folder = ""
# #     if run_dir and run_dir.exists():
# #         report_folder = str(run_dir)
# #
# #         html = next(run_dir.glob("*.html"), None)
# #         docx = next(run_dir.glob("*.docx"), None)
# #         pptx = next(run_dir.glob("*.pptx"), None)
# #         md = next(run_dir.glob("*.md"), None)
# #
# #         def to_report_url(p: Path | None) -> str | None:
# #             if not p:
# #                 return None
# #             rel = p.relative_to(REPORTS_BASE).as_posix()
# #             return url_for("serve_report", relpath=rel)
# #
# #         generated = {
# #             "html": to_report_url(html),
# #             "docx": to_report_url(docx),
# #             "pptx": to_report_url(pptx),
# #             "md": to_report_url(md),
# #         }
# #
# #     # File display text for the report page
# #     file_display = Path(file_raw).name if file_raw else "(auto from INI)"
# #
# #     # If EXE failed, show stderr/stdout in a professional error view
# #     if proc.returncode != 0:
# #         return render_template(
# #             "result.html",
# #             competitor=competitor_norm,
# #             baseline=baseline_norm,
# #             file_path=file_display,
# #             generated_at=generated_at,
# #             report_folder=report_folder,
# #             generated=generated,
# #             exit_code=proc.returncode,
# #             stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# #             stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# #             status="failed",
# #         ), 500
# #     return render_template(
# #         "result.html",
# #         competitor=competitor_norm,
# #         baseline=baseline_norm,
# #         generated_at=generated_at,
# #         generated=generated,
# #         exit_code=proc.returncode,
# #         stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# #         stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# #         status="failed",
# #     ), 500
# #     return render_template(
# #         "result.html",
# #         competitor=competitor_norm,
# #         baseline=baseline_norm,
# #         generated_at=generated_at,
# #         generated=generated,
# #         exit_code=proc.returncode,
# #         status="ok",
# #         duration_seconds=int((finished - started).total_seconds()),
# #     )
# #     # return render_template(
# #     #     "result.html",
# #     #     competitor=competitor_norm,
# #     #     baseline=baseline_norm,
# #     #     file_path=file_display,
# #     #     generated_at=generated_at,
# #     #     report_folder=report_folder,
# #     #     generated=generated,
# #     #     exit_code=proc.returncode,
# #     #     stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# #     #     stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# #     #     status="ok",
# #     #     duration_seconds=int((finished - started).total_seconds()),
# #     # )
# #
# # # def run_analysis():
# # #     competitor_raw = request.form.get("competitor", "").strip()
# # #     baseline_raw = request.form.get("baseline", "").strip()
# # #     file_raw = request.form.get("file", "").strip()
# # #
# # #     # Normalize inputs
# # #     competitor_norm = normalize_url_guess_com(competitor_raw)
# # #     baseline_norm = normalize_url_guess_com(baseline_raw) if baseline_raw else ""
# # #
# # #     if not competitor_norm:
# # #         return render_template("index.html", error="Competitor is required."), 400
# # #
# # #     # Build command
# # #     cmd = [str(EXE_PATH), "--competitor", competitor_norm]
# # #     if baseline_norm:
# # #         cmd += ["--baseline", baseline_norm]
# # #     if file_raw:
# # #         cmd += ["--file", file_raw]
# # #
# # #     # Track what folder existed BEFORE run, so we can reliably detect the new run folder
# # #     before = set()
# # #     if REPORTS_BASE.exists():
# # #         before = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
# # #
# # #     # Execute
# # #     started = datetime.now()
# # #     try:
# # #         proc = subprocess.run(
# # #             cmd,
# # #             capture_output=True,
# # #             text=True,
# # #             cwd=str(EXE_PATH.parent),
# # #             timeout=60 * 30,  # 30 minutes safety
# # #         )
# # #     except FileNotFoundError:
# # #         return render_template("index.html", error=f"EXE not found: {EXE_PATH}"), 500
# # #     except subprocess.TimeoutExpired:
# # #         return render_template("index.html", error="Execution timed out."), 500
# # #     except Exception as e:
# # #         return render_template("index.html", error=f"Failed to execute: {e}"), 500
# # #
# # #     finished = datetime.now()
# # #     generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
# # #
# # #     # Detect the new report folder
# # #     run_dir = None
# # #     if REPORTS_BASE.exists():
# # #         after = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
# # #         created = sorted(list(after - before))
# # #         if created:
# # #             # pick newest among newly created
# # #             candidates = [REPORTS_BASE / name for name in created]
# # #             run_dir = max(candidates, key=lambda p: p.stat().st_mtime)
# # #         else:
# # #             # fallback: newest overall
# # #             run_dir = newest_report_run_dir(REPORTS_BASE)
# # #
# # #     generated = {"html": None, "docx": None, "pptx": None, "md": None}
# # #     report_folder = ""
# # #     if run_dir and run_dir.exists():
# # #         report_folder = str(run_dir)
# # #
# # #         html = next(run_dir.glob("*.html"), None)
# # #         docx = next(run_dir.glob("*.docx"), None)
# # #         pptx = next(run_dir.glob("*.pptx"), None)
# # #         md = next(run_dir.glob("*.md"), None)
# # #
# # #         def to_report_url(p: Path | None) -> str | None:
# # #             if not p:
# # #                 return None
# # #             rel = p.relative_to(REPORTS_BASE).as_posix()
# # #             return url_for("serve_report", relpath=rel)
# # #
# # #         generated = {
# # #             "html": to_report_url(html),
# # #             "docx": to_report_url(docx),
# # #             "pptx": to_report_url(pptx),
# # #             "md": to_report_url(md),
# # #         }
# # #
# # #     # File display text for the report page
# # #     file_display = Path(file_raw).name if file_raw else "(auto from INI)"
# # #
# # #     # If EXE failed, show stderr/stdout in a professional error view
# # #     if proc.returncode != 0:
# # #         return render_template(
# # #             "result.html",
# # #             competitor=competitor_norm,
# # #             baseline=baseline_norm,
# # #             file_path=file_display,
# # #             generated_at=generated_at,
# # #             report_folder=report_folder,
# # #             generated=generated,
# # #             exit_code=proc.returncode,
# # #             stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# # #             stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# # #             status="failed",
# # #         ), 500
# # #     return render_template(
# # #         "result.html",
# # #         competitor=competitor_norm,
# # #         baseline=baseline_norm,
# # #         generated_at=generated_at,
# # #         generated=generated,
# # #         exit_code=proc.returncode,
# # #         stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# # #         stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# # #         status="failed",
# # #     ), 500
# # #     return render_template(
# # #         "result.html",
# # #         competitor=competitor_norm,
# # #         baseline=baseline_norm,
# # #         generated_at=generated_at,
# # #         generated=generated,
# # #         exit_code=proc.returncode,
# # #         status="ok",
# # #         duration_seconds=int((finished - started).total_seconds()),
# # #     )
# # #     # return render_template(
# # #     #     "result.html",
# # #     #     competitor=competitor_norm,
# # #     #     baseline=baseline_norm,
# # #     #     file_path=file_display,
# # #     #     generated_at=generated_at,
# # #     #     report_folder=report_folder,
# # #     #     generated=generated,
# # #     #     exit_code=proc.returncode,
# # #     #     stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# # #     #     stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# # #     #     status="ok",
# # #     #     duration_seconds=int((finished - started).total_seconds()),
# # #     # )
# #
# #
# #
# #
# # if __name__ == "__main__":
# #     app.run(host="127.0.0.1", port=5000, debug=True)
# #
# # ##################################################
# #
# #
# #
# #
# # # import os
# # # import re
# # # import shutil
# # # import subprocess
# # # from datetime import datetime
# # # from pathlib import Path
# # # from flask import Flask, render_template, request, send_from_directory, abort
# # # from flask import send_from_directory, abort
# # # from pathlib import Path
# # #
# # # app = Flask(__name__)
# # #
# # # # Path to your EXE
# # # EXE_PATH = r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\TitaniumTechnologyGapAnalysis.exe"
# # #
# # # # Where your EXE writes reports (per your INI you showed)
# # # REPORTS_ROOT = r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\reports"
# # #
# # # # Where the web ui will publish copies so the browser can download/view them
# # # PUBLISHED_RUNS_DIR = Path(app.root_path) / "static" / "runs"
# # # PUBLISHED_RUNS_DIR.mkdir(parents=True, exist_ok=True)
# # #
# # #
# # # # Point this to the SAME reports folder your EXE writes to.
# # # # Example based on your logs:
# # # REPORTS_BASE = Path(r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\reports")
# # #
# # # @app.get("/reports/<path:relpath>")
# # # def serve_report(relpath: str):
# # #     # Prevent path traversal
# # #     rel = Path(relpath)
# # #     full = (REPORTS_BASE / rel).resolve()
# # #
# # #     base = REPORTS_BASE.resolve()
# # #     if base not in full.parents and full != base:
# # #         abort(403)
# # #
# # #     if not full.exists() or not full.is_file():
# # #         abort(404)
# # #
# # #     return send_from_directory(full.parent, full.name, as_attachment=False)
# # #
# # #
# # #
# # # def normalize_url_basic(url: str) -> str:
# # #     s = (url or "").strip()
# # #     if not s:
# # #         return ""
# # #     if re.match(r"^https?://", s, flags=re.IGNORECASE):
# # #         return s
# # #     return "https://" + s
# # #
# # #
# # # def run_exe(competitor: str, baseline: str | None, file_path: str | None) -> dict:
# # #     competitor = normalize_url_basic(competitor)
# # #     baseline = normalize_url_basic(baseline or "")
# # #
# # #     if not competitor:
# # #         raise ValueError("Competitor is required.")
# # #     if "." not in competitor.replace("https://", "").replace("http://", ""):
# # #         raise ValueError("Competitor must be a valid domain (example: tektelic.com).")
# # #
# # #     cmd = [EXE_PATH, "--competitor", competitor]
# # #     if baseline:
# # #         cmd += ["--baseline", baseline]
# # #     if file_path:
# # #         cmd += ["--file", file_path]
# # #
# # #     # Run the EXE
# # #     proc = subprocess.run(
# # #         cmd,
# # #         capture_output=True,
# # #         text=True,
# # #         shell=False
# # #     )
# # #
# # #     stdout = proc.stdout or ""
# # #     stderr = proc.stderr or ""
# # #
# # #     return {
# # #         "cmd": " ".join(cmd),
# # #         "exit_code": proc.returncode,
# # #         "stdout": stdout,
# # #         "stderr": stderr,
# # #     }
# # #
# # #
# # # def parse_saved_paths(stdout: str) -> dict:
# # #     """
# # #     Your EXE logs lines like:
# # #       Saved Markdown: C:\...\comparison_report_xxx.md
# # #       Saved HTML:    C:\...\comparison_report_xxx.html
# # #       Saved Word:    C:\...\comparison_report_xxx.docx
# # #       Saved PowerPoint: C:\...\comparison_report_xxx.pptx
# # #
# # #     We parse those absolute paths.
# # #     """
# # #     out = {}
# # #
# # #     patterns = {
# # #         "md": r"Saved Markdown:\s*(.+)$",
# # #         "html": r"Saved HTML:\s*(.+)$",
# # #         "docx": r"Saved Word:\s*(.+)$",
# # #         "pptx": r"Saved PowerPoint:\s*(.+)$",
# # #     }
# # #
# # #     for key, pat in patterns.items():
# # #         m = re.search(pat, stdout, flags=re.MULTILINE)
# # #         if m:
# # #             out[key] = m.group(1).strip()
# # #
# # #     return out
# # #
# # #
# # # def publish_run_files(saved_paths: dict) -> dict:
# # #     """
# # #     Copy the generated files into static/runs/<run_id>/ so Flask can serve them.
# # #     Returns URLs (relative) you can render into HTML.
# # #     """
# # #     run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
# # #     run_dir = PUBLISHED_RUNS_DIR / run_id
# # #     run_dir.mkdir(parents=True, exist_ok=True)
# # #
# # #     published = {"run_id": run_id, "files": {}}
# # #
# # #     for ext, src in saved_paths.items():
# # #         src_path = Path(src)
# # #         if src_path.exists():
# # #             dst_path = run_dir / src_path.name
# # #             shutil.copy2(src_path, dst_path)
# # #             published["files"][ext] = {
# # #                 "name": dst_path.name,
# # #                 "url": f"/static/runs/{run_id}/{dst_path.name}",
# # #                 "path": str(dst_path),
# # #             }
# # #
# # #     return published
# # #
# # #
# # # @app.get("/")
# # # def index():
# # #     return render_template("index.html")
# # #
# # #
# # # @app.post("/run")
# # # def run_analysis():
# # #     competitor = request.form.get("competitor", "").strip()
# # #     baseline = request.form.get("baseline", "").strip()
# # #     file_path = request.form.get("file", "").strip()  # optional
# # #
# # #     try:
# # #         result = run_exe(competitor, baseline, file_path)
# # #         saved = parse_saved_paths(result["stdout"])
# # #         published = publish_run_files(saved)
# # #
# # #         # If we have an HTML report, we can embed it in an iframe
# # #         html_url = published["files"].get("html", {}).get("url")
# # #
# # #         return render_template(
# # #             "result.html",
# # #             competitor=normalize_url_basic(competitor),
# # #             baseline=normalize_url_basic(baseline) if baseline else "",
# # #             file_path=file_path or "(auto from INI)",
# # #             exit_code=result["exit_code"],
# # #             cmd=result["cmd"],
# # #             stdout_tail="\n".join((result["stdout"] or "").splitlines()[-30:]),
# # #             stderr_tail="\n".join((result["stderr"] or "").splitlines()[-30:]),
# # #             published=published,
# # #             html_url=html_url,
# # #         )
# # #
# # #     except Exception as e:
# # #         return render_template("index.html", error=str(e)), 400
# # #
# # #
# # # if __name__ == "__main__":
# # #     app.run(host="127.0.0.1", port=5000, debug=True)




#
# import re
# from flask import Flask, render_template, request
#
# app = Flask(__name__)
#
#
# # {
# #   "baseline_raw": "door.com",
# #   "competitor_normalized": "https://tektelic.com",
# #   "competitor_raw": "https://tektelic.com",
# #   "file_raw": "",
# #   "next_step": "execute TitaniumTechnologyGapAnalysis.exe via subprocess",
# #   "status": "ok"
# # }
# #
#
# def normalize_competitor(s: str) -> str:
#     """
#     Accepts:
#       - door.com
#       - https://door.com
#       - door
#
#     Produces:
#       - https://door.com
#
#     IMPORTANT:
#     - If user types "door" (no dot), we DO NOT guess ".com"
#     - This prevents DNS errors like https://door
#     """
#     s = (s or "").strip()
#     if not s:
#         raise ValueError("Competitor is required.")
#
#     # Already has http/https
#     if re.match(r"^https?://", s, flags=re.IGNORECASE):
#         return s
#
#     # No dot = invalid domain
#     if "." not in s:
#         raise ValueError("Competitor must be a valid domain (example: door.com).")
#
#     return "https://" + s
#
#
# @app.get("/")
# def index():
#     return render_template("index.html")
#
#
# @app.post("/run")
# def run():
#     competitor = request.form.get("competitor", "")
#     baseline = request.form.get("baseline", "")
#     file_path = request.form.get("file", "")
#
#     try:
#         competitor_norm = normalize_competitor(competitor)
#     except Exception as e:
#         return render_template("index.html", error=str(e)), 400
#
#     # STEP 1 ONLY:
#     # Do NOT execute TitaniumTechnologyGapAnalysis yet
#     return {
#         "status": "ok",
#         "competitor_raw": competitor,
#         "competitor_normalized": competitor_norm,
#         "baseline_raw": baseline,
#         "file_raw": file_path,
#         "next_step": "execute TitaniumTechnologyGapAnalysis.exe via subprocess",
#     }
#
#
# if __name__ == "__main__":
#     app.run(host="127.0.0.1", port=5000, debug=True)
#
#
# # import re
# # import subprocess
# # from datetime import datetime
# # from pathlib import Path
# # from typing import Optional
# #
# # from flask import Flask, render_template, request, url_for, send_from_directory, abort
# #
# # app = Flask(__name__)
# #
# # # MUST match where your EXE writes reports (per your log).
# # REPORTS_BASE = Path(
# #     r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\reports"
# # )
# #
# # # Path to your EXE
# # EXE_PATH = Path(
# #     r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\TitaniumTechnologyGapAnalysis.exe"
# # )
# #
# #
# # # -----------------------------
# # # Input normalization
# # # -----------------------------
# # def normalize_url_guess_com(s: str) -> str:
# #     """
# #     Accepts:
# #       - door.com
# #       - https://door.com
# #       - door          (guesses .com)
# #       - tektelic.com/path
# #     Produces:
# #       - https://door.com
# #       - https://tektelic.com/path
# #     """
# #     s = (s or "").strip()
# #     if not s:
# #         return ""
# #
# #     # Keep if already has scheme
# #     if re.match(r"^https?://", s, flags=re.IGNORECASE):
# #         return s
# #
# #     # Split host/path
# #     parts = s.split("/", 1)
# #     host = parts[0].strip()
# #     rest = ("/" + parts[1]) if len(parts) > 1 else ""
# #
# #     # Guess .com if no dot (except localhost)
# #     if "." not in host and host.lower() not in {"localhost"}:
# #         host = host + ".com"
# #
# #     return "https://" + host + rest
# #
# #
# # # -----------------------------
# # # Report folder detection
# # # -----------------------------
# # def newest_report_run_dir(reports_base: Path) -> Optional[Path]:
# #     if not reports_base.exists():
# #         return None
# #     dirs = [p for p in reports_base.iterdir() if p.is_dir()]
# #     if not dirs:
# #         return None
# #     return max(dirs, key=lambda p: p.stat().st_mtime)
# #
# #
# # def detect_new_run_dir(reports_base: Path, before_dirs: set[str]) -> Optional[Path]:
# #     """
# #     Detects a newly-created run directory after the EXE runs.
# #     Falls back to newest overall if nothing new was created (rare).
# #     """
# #     if not reports_base.exists():
# #         return None
# #
# #     after_dirs = {p.name for p in reports_base.iterdir() if p.is_dir()}
# #     created = [reports_base / name for name in (after_dirs - before_dirs)]
# #     if created:
# #         return max(created, key=lambda p: p.stat().st_mtime)
# #
# #     return newest_report_run_dir(reports_base)
# #
# #
# # # -----------------------------
# # # Safe serving of generated reports
# # # -----------------------------
# # @app.get("/reports/<path:relpath>")
# # def serve_report(relpath: str):
# #     """
# #     Serves generated reports from disk so the browser can load them (iframe / downloads).
# #     """
# #     rel = Path(relpath)
# #     full = (REPORTS_BASE / rel).resolve()
# #     base = REPORTS_BASE.resolve()
# #
# #     # Path traversal protection
# #     if base not in full.parents and full != base:
# #         abort(403)
# #
# #     if not full.exists() or not full.is_file():
# #         abort(404)
# #
# #     # For HTML preview: as_attachment=False
# #     return send_from_directory(full.parent, full.name, as_attachment=False)
# #
# #
# # # -----------------------------
# # # Pages
# # # -----------------------------
# # @app.get("/")
# # def index():
# #     return render_template("index.html")
# #
# #
# # @app.post("/run")
# # def run_analysis():
# #     competitor_raw = request.form.get("competitor", "").strip()
# #     baseline_raw = request.form.get("baseline", "").strip()
# #     file_raw = request.form.get("file", "").strip()
# #
# #     competitor_norm = normalize_url_guess_com(competitor_raw)
# #     baseline_norm = normalize_url_guess_com(baseline_raw) if baseline_raw else ""
# #
# #     if not competitor_norm:
# #         return render_template("index.html", error="Competitor is required."), 400
# #
# #     # Build command
# #     cmd = [str(EXE_PATH), "--competitor", competitor_norm]
# #     if baseline_norm:
# #         cmd += ["--baseline", baseline_norm]
# #     if file_raw:
# #         cmd += ["--file", file_raw]
# #
# #     # Validate EXE path early
# #     if not EXE_PATH.exists():
# #         return render_template("index.html", error=f"EXE not found: {EXE_PATH}"), 500
# #
# #     # Track report directories BEFORE run
# #     before_dirs = set()
# #     if REPORTS_BASE.exists():
# #         before_dirs = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
# #
# #     started = datetime.now()
# #
# #     # Execute
# #     try:
# #         proc = subprocess.run(
# #             cmd,
# #             capture_output=True,
# #             text=True,
# #             cwd=str(EXE_PATH.parent),
# #             timeout=60 * 30,  # 30 minutes
# #         )
# #     except subprocess.TimeoutExpired:
# #         return render_template("index.html", error="Execution timed out."), 500
# #     except Exception as e:
# #         return render_template("index.html", error=f"Failed to execute: {e}"), 500
# #
# #     finished = datetime.now()
# #     generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
# #     duration_seconds = int((finished - started).total_seconds())
# #
# #     # Detect run dir + generated artifacts
# #     run_dir = detect_new_run_dir(REPORTS_BASE, before_dirs)
# #
# #     generated = {"html": None, "docx": None, "pptx": None, "md": None}
# #     if run_dir and run_dir.exists():
# #         html = next(run_dir.glob("*.html"), None)
# #         docx = next(run_dir.glob("*.docx"), None)
# #         pptx = next(run_dir.glob("*.pptx"), None)
# #         md = next(run_dir.glob("*.md"), None)
# #
# #         def to_report_url(p: Optional[Path]) -> Optional[str]:
# #             if not p:
# #                 return None
# #             rel = p.relative_to(REPORTS_BASE).as_posix()
# #             return url_for("serve_report", relpath=rel)
# #
# #         generated = {
# #             "html": to_report_url(html),
# #             "docx": to_report_url(docx),
# #             "pptx": to_report_url(pptx),
# #             "md": to_report_url(md),
# #         }
# #
# #     # Diagnostics tails (render only if failed; your template should hide on success)
# #     stdout_tail = "\n".join((proc.stdout or "").splitlines()[-40:])
# #     stderr_tail = "\n".join((proc.stderr or "").splitlines()[-40:])
# #
# #     # FAIL path
# #     if proc.returncode != 0:
# #         return render_template(
# #             "result.html",
# #             status="failed",
# #             competitor=competitor_norm,
# #             baseline=baseline_norm,
# #             generated_at=generated_at,
# #             duration_seconds=duration_seconds,
# #             exit_code=proc.returncode,
# #             generated=generated,
# #             stdout_tail=stdout_tail,
# #             stderr_tail=stderr_tail,
# #         ), 500
# #
# #     # OK path
# #     return render_template(
# #         "result.html",
# #         status="ok",
# #         competitor=competitor_norm,
# #         baseline=baseline_norm,
# #         generated_at=generated_at,
# #         duration_seconds=duration_seconds,
# #         exit_code=0,
# #         generated=generated,
# #     )
# #
# #
# # if __name__ == "__main__":
# #     # Local dev only
# #     app.run(host="127.0.0.1", port=5000, debug=True)
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# # # import os
# # # import re
# # # import subprocess
# # # from datetime import datetime
# # # from pathlib import Path
# # #
# # # from flask import Flask, render_template, request, url_for, send_from_directory, abort
# # #
# # # app = Flask(__name__)
# # #
# # # # MUST match where your EXE writes reports (per your log).
# # # REPORTS_BASE = Path(
# # #     r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\reports"
# # # )
# # #
# # # # Path to your EXE
# # # EXE_PATH = Path(
# # #     r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\TitaniumTechnologyGapAnalysis.exe"
# # # )
# # #
# # #
# # # def normalize_url_guess_com(s: str) -> str:
# # #     """
# # #     Accepts:
# # #       - door.com
# # #       - https://door.com
# # #       - door          (we will guess .com here, per your latest script behavior)
# # #     Produces:
# # #       - https://door.com
# # #     """
# # #     s = (s or "").strip()
# # #     if not s:
# # #         return ""
# # #
# # #     if re.match(r"^https?://", s, flags=re.IGNORECASE):
# # #         return s
# # #
# # #     parts = s.split("/", 1)
# # #     host = parts[0].strip()
# # #     rest = ("/" + parts[1]) if len(parts) > 1 else ""
# # #
# # #     if "." not in host and host.lower() not in {"localhost"}:
# # #         host = host + ".com"
# # #
# # #     return "https://" + host + rest
# # #
# # #
# # # def newest_report_run_dir(reports_base: Path) -> Path | None:
# # #     if not reports_base.exists():
# # #         return None
# # #     dirs = [p for p in reports_base.iterdir() if p.is_dir()]
# # #     if not dirs:
# # #         return None
# # #     return max(dirs, key=lambda p: p.stat().st_mtime)
# # #
# # #
# # # @app.get("/reports/<path:relpath>")
# # # def serve_report(relpath: str):
# # #     """
# # #     Serves generated reports from disk so the browser can load them (iframe / downloads).
# # #     """
# # #     rel = Path(relpath)
# # #     full = (REPORTS_BASE / rel).resolve()
# # #     base = REPORTS_BASE.resolve()
# # #
# # #     # Path traversal protection
# # #     if base not in full.parents and full != base:
# # #         abort(403)
# # #
# # #     if not full.exists() or not full.is_file():
# # #         abort(404)
# # #
# # #     # For HTML preview: as_attachment=False
# # #     return send_from_directory(full.parent, full.name, as_attachment=False)
# # #
# # #
# # # @app.get("/")
# # # def index():
# # #     return render_template("index.html")
# # #
# # #
# # # @app.post("/run")
# # # def run_analysis():
# # #     competitor_raw = request.form.get("competitor", "").strip()
# # #     baseline_raw = request.form.get("baseline", "").strip()
# # #     file_raw = request.form.get("file", "").strip()
# # #
# # #     # Normalize inputs
# # #     competitor_norm = normalize_url_guess_com(competitor_raw)
# # #     baseline_norm = normalize_url_guess_com(baseline_raw) if baseline_raw else ""
# # #
# # #     if not competitor_norm:
# # #         return render_template("index.html", error="Competitor is required."), 400
# # #
# # #     # Build command
# # #     cmd = [str(EXE_PATH), "--competitor", competitor_norm]
# # #     if baseline_norm:
# # #         cmd += ["--baseline", baseline_norm]
# # #     if file_raw:
# # #         cmd += ["--file", file_raw]
# # #
# # #     # Track what folder existed BEFORE run, so we can reliably detect the new run folder
# # #     before = set()
# # #     if REPORTS_BASE.exists():
# # #         before = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
# # #
# # #     # Execute
# # #     started = datetime.now()
# # #     try:
# # #         proc = subprocess.run(
# # #             cmd,
# # #             capture_output=True,
# # #             text=True,
# # #             cwd=str(EXE_PATH.parent),
# # #             timeout=60 * 30,  # 30 minutes safety
# # #         )
# # #     except FileNotFoundError:
# # #         return render_template("index.html", error=f"EXE not found: {EXE_PATH}"), 500
# # #     except subprocess.TimeoutExpired:
# # #         return render_template("index.html", error="Execution timed out."), 500
# # #     except Exception as e:
# # #         return render_template("index.html", error=f"Failed to execute: {e}"), 500
# # #
# # #     finished = datetime.now()
# # #     generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
# # #
# # #     # Detect the new report folder
# # #     run_dir = None
# # #     if REPORTS_BASE.exists():
# # #         after = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
# # #         created = sorted(list(after - before))
# # #         if created:
# # #             # pick newest among newly created
# # #             candidates = [REPORTS_BASE / name for name in created]
# # #             run_dir = max(candidates, key=lambda p: p.stat().st_mtime)
# # #         else:
# # #             # fallback: newest overall
# # #             run_dir = newest_report_run_dir(REPORTS_BASE)
# # #
# # #     generated = {"html": None, "docx": None, "pptx": None, "md": None}
# # #     report_folder = ""
# # #     if run_dir and run_dir.exists():
# # #         report_folder = str(run_dir)
# # #
# # #         html = next(run_dir.glob("*.html"), None)
# # #         docx = next(run_dir.glob("*.docx"), None)
# # #         pptx = next(run_dir.glob("*.pptx"), None)
# # #         md = next(run_dir.glob("*.md"), None)
# # #
# # #         def to_report_url(p: Path | None) -> str | None:
# # #             if not p:
# # #                 return None
# # #             rel = p.relative_to(REPORTS_BASE).as_posix()
# # #             return url_for("serve_report", relpath=rel)
# # #
# # #         generated = {
# # #             "html": to_report_url(html),
# # #             "docx": to_report_url(docx),
# # #             "pptx": to_report_url(pptx),
# # #             "md": to_report_url(md),
# # #         }
# # #
# # #     # File display text for the report page
# # #     file_display = Path(file_raw).name if file_raw else "(auto from INI)"
# # #
# # #     # If EXE failed, show stderr/stdout in a professional error view
# # #     if proc.returncode != 0:
# # #         return render_template(
# # #             "result.html",
# # #             competitor=competitor_norm,
# # #             baseline=baseline_norm,
# # #             file_path=file_display,
# # #             generated_at=generated_at,
# # #             report_folder=report_folder,
# # #             generated=generated,
# # #             exit_code=proc.returncode,
# # #             stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# # #             stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# # #             status="failed",
# # #         ), 500
# # #     return render_template(
# # #         "result.html",
# # #         competitor=competitor_norm,
# # #         baseline=baseline_norm,
# # #         generated_at=generated_at,
# # #         generated=generated,
# # #         exit_code=proc.returncode,
# # #         stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# # #         stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# # #         status="failed",
# # #     ), 500
# # #     return render_template(
# # #         "result.html",
# # #         competitor=competitor_norm,
# # #         baseline=baseline_norm,
# # #         generated_at=generated_at,
# # #         generated=generated,
# # #         exit_code=proc.returncode,
# # #         status="ok",
# # #         duration_seconds=int((finished - started).total_seconds()),
# # #     )
# # #     # return render_template(
# # #     #     "result.html",
# # #     #     competitor=competitor_norm,
# # #     #     baseline=baseline_norm,
# # #     #     file_path=file_display,
# # #     #     generated_at=generated_at,
# # #     #     report_folder=report_folder,
# # #     #     generated=generated,
# # #     #     exit_code=proc.returncode,
# # #     #     stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# # #     #     stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# # #     #     status="ok",
# # #     #     duration_seconds=int((finished - started).total_seconds()),
# # #     # )
# # #
# # # # def run_analysis():
# # # #     competitor_raw = request.form.get("competitor", "").strip()
# # # #     baseline_raw = request.form.get("baseline", "").strip()
# # # #     file_raw = request.form.get("file", "").strip()
# # # #
# # # #     # Normalize inputs
# # # #     competitor_norm = normalize_url_guess_com(competitor_raw)
# # # #     baseline_norm = normalize_url_guess_com(baseline_raw) if baseline_raw else ""
# # # #
# # # #     if not competitor_norm:
# # # #         return render_template("index.html", error="Competitor is required."), 400
# # # #
# # # #     # Build command
# # # #     cmd = [str(EXE_PATH), "--competitor", competitor_norm]
# # # #     if baseline_norm:
# # # #         cmd += ["--baseline", baseline_norm]
# # # #     if file_raw:
# # # #         cmd += ["--file", file_raw]
# # # #
# # # #     # Track what folder existed BEFORE run, so we can reliably detect the new run folder
# # # #     before = set()
# # # #     if REPORTS_BASE.exists():
# # # #         before = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
# # # #
# # # #     # Execute
# # # #     started = datetime.now()
# # # #     try:
# # # #         proc = subprocess.run(
# # # #             cmd,
# # # #             capture_output=True,
# # # #             text=True,
# # # #             cwd=str(EXE_PATH.parent),
# # # #             timeout=60 * 30,  # 30 minutes safety
# # # #         )
# # # #     except FileNotFoundError:
# # # #         return render_template("index.html", error=f"EXE not found: {EXE_PATH}"), 500
# # # #     except subprocess.TimeoutExpired:
# # # #         return render_template("index.html", error="Execution timed out."), 500
# # # #     except Exception as e:
# # # #         return render_template("index.html", error=f"Failed to execute: {e}"), 500
# # # #
# # # #     finished = datetime.now()
# # # #     generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")
# # # #
# # # #     # Detect the new report folder
# # # #     run_dir = None
# # # #     if REPORTS_BASE.exists():
# # # #         after = {p.name for p in REPORTS_BASE.iterdir() if p.is_dir()}
# # # #         created = sorted(list(after - before))
# # # #         if created:
# # # #             # pick newest among newly created
# # # #             candidates = [REPORTS_BASE / name for name in created]
# # # #             run_dir = max(candidates, key=lambda p: p.stat().st_mtime)
# # # #         else:
# # # #             # fallback: newest overall
# # # #             run_dir = newest_report_run_dir(REPORTS_BASE)
# # # #
# # # #     generated = {"html": None, "docx": None, "pptx": None, "md": None}
# # # #     report_folder = ""
# # # #     if run_dir and run_dir.exists():
# # # #         report_folder = str(run_dir)
# # # #
# # # #         html = next(run_dir.glob("*.html"), None)
# # # #         docx = next(run_dir.glob("*.docx"), None)
# # # #         pptx = next(run_dir.glob("*.pptx"), None)
# # # #         md = next(run_dir.glob("*.md"), None)
# # # #
# # # #         def to_report_url(p: Path | None) -> str | None:
# # # #             if not p:
# # # #                 return None
# # # #             rel = p.relative_to(REPORTS_BASE).as_posix()
# # # #             return url_for("serve_report", relpath=rel)
# # # #
# # # #         generated = {
# # # #             "html": to_report_url(html),
# # # #             "docx": to_report_url(docx),
# # # #             "pptx": to_report_url(pptx),
# # # #             "md": to_report_url(md),
# # # #         }
# # # #
# # # #     # File display text for the report page
# # # #     file_display = Path(file_raw).name if file_raw else "(auto from INI)"
# # # #
# # # #     # If EXE failed, show stderr/stdout in a professional error view
# # # #     if proc.returncode != 0:
# # # #         return render_template(
# # # #             "result.html",
# # # #             competitor=competitor_norm,
# # # #             baseline=baseline_norm,
# # # #             file_path=file_display,
# # # #             generated_at=generated_at,
# # # #             report_folder=report_folder,
# # # #             generated=generated,
# # # #             exit_code=proc.returncode,
# # # #             stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# # # #             stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# # # #             status="failed",
# # # #         ), 500
# # # #     return render_template(
# # # #         "result.html",
# # # #         competitor=competitor_norm,
# # # #         baseline=baseline_norm,
# # # #         generated_at=generated_at,
# # # #         generated=generated,
# # # #         exit_code=proc.returncode,
# # # #         stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# # # #         stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# # # #         status="failed",
# # # #     ), 500
# # # #     return render_template(
# # # #         "result.html",
# # # #         competitor=competitor_norm,
# # # #         baseline=baseline_norm,
# # # #         generated_at=generated_at,
# # # #         generated=generated,
# # # #         exit_code=proc.returncode,
# # # #         status="ok",
# # # #         duration_seconds=int((finished - started).total_seconds()),
# # # #     )
# # # #     # return render_template(
# # # #     #     "result.html",
# # # #     #     competitor=competitor_norm,
# # # #     #     baseline=baseline_norm,
# # # #     #     file_path=file_display,
# # # #     #     generated_at=generated_at,
# # # #     #     report_folder=report_folder,
# # # #     #     generated=generated,
# # # #     #     exit_code=proc.returncode,
# # # #     #     stdout_tail="\n".join((proc.stdout or "").splitlines()[-40:]),
# # # #     #     stderr_tail="\n".join((proc.stderr or "").splitlines()[-40:]),
# # # #     #     status="ok",
# # # #     #     duration_seconds=int((finished - started).total_seconds()),
# # # #     # )
# # #
# # #
# # #
# # #
# # # if __name__ == "__main__":
# # #     app.run(host="127.0.0.1", port=5000, debug=True)
# # #
# # # ##################################################
# # #
# # #
# # #
# # #
# # # # import os
# # # # import re
# # # # import shutil
# # # # import subprocess
# # # # from datetime import datetime
# # # # from pathlib import Path
# # # # from flask import Flask, render_template, request, send_from_directory, abort
# # # # from flask import send_from_directory, abort
# # # # from pathlib import Path
# # # #
# # # # app = Flask(__name__)
# # # #
# # # # # Path to your EXE
# # # # EXE_PATH = r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\TitaniumTechnologyGapAnalysis.exe"
# # # #
# # # # # Where your EXE writes reports (per your INI you showed)
# # # # REPORTS_ROOT = r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\reports"
# # # #
# # # # # Where the web ui will publish copies so the browser can download/view them
# # # # PUBLISHED_RUNS_DIR = Path(app.root_path) / "static" / "runs"
# # # # PUBLISHED_RUNS_DIR.mkdir(parents=True, exist_ok=True)
# # # #
# # # #
# # # # # Point this to the SAME reports folder your EXE writes to.
# # # # # Example based on your logs:
# # # # REPORTS_BASE = Path(r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\reports")
# # # #
# # # # @app.get("/reports/<path:relpath>")
# # # # def serve_report(relpath: str):
# # # #     # Prevent path traversal
# # # #     rel = Path(relpath)
# # # #     full = (REPORTS_BASE / rel).resolve()
# # # #
# # # #     base = REPORTS_BASE.resolve()
# # # #     if base not in full.parents and full != base:
# # # #         abort(403)
# # # #
# # # #     if not full.exists() or not full.is_file():
# # # #         abort(404)
# # # #
# # # #     return send_from_directory(full.parent, full.name, as_attachment=False)
# # # #
# # # #
# # # #
# # # # def normalize_url_basic(url: str) -> str:
# # # #     s = (url or "").strip()
# # # #     if not s:
# # # #         return ""
# # # #     if re.match(r"^https?://", s, flags=re.IGNORECASE):
# # # #         return s
# # # #     return "https://" + s
# # # #
# # # #
# # # # def run_exe(competitor: str, baseline: str | None, file_path: str | None) -> dict:
# # # #     competitor = normalize_url_basic(competitor)
# # # #     baseline = normalize_url_basic(baseline or "")
# # # #
# # # #     if not competitor:
# # # #         raise ValueError("Competitor is required.")
# # # #     if "." not in competitor.replace("https://", "").replace("http://", ""):
# # # #         raise ValueError("Competitor must be a valid domain (example: tektelic.com).")
# # # #
# # # #     cmd = [EXE_PATH, "--competitor", competitor]
# # # #     if baseline:
# # # #         cmd += ["--baseline", baseline]
# # # #     if file_path:
# # # #         cmd += ["--file", file_path]
# # # #
# # # #     # Run the EXE
# # # #     proc = subprocess.run(
# # # #         cmd,
# # # #         capture_output=True,
# # # #         text=True,
# # # #         shell=False
# # # #     )
# # # #
# # # #     stdout = proc.stdout or ""
# # # #     stderr = proc.stderr or ""
# # # #
# # # #     return {
# # # #         "cmd": " ".join(cmd),
# # # #         "exit_code": proc.returncode,
# # # #         "stdout": stdout,
# # # #         "stderr": stderr,
# # # #     }
# # # #
# # # #
# # # # def parse_saved_paths(stdout: str) -> dict:
# # # #     """
# # # #     Your EXE logs lines like:
# # # #       Saved Markdown: C:\...\comparison_report_xxx.md
# # # #       Saved HTML:    C:\...\comparison_report_xxx.html
# # # #       Saved Word:    C:\...\comparison_report_xxx.docx
# # # #       Saved PowerPoint: C:\...\comparison_report_xxx.pptx
# # # #
# # # #     We parse those absolute paths.
# # # #     """
# # # #     out = {}
# # # #
# # # #     patterns = {
# # # #         "md": r"Saved Markdown:\s*(.+)$",
# # # #         "html": r"Saved HTML:\s*(.+)$",
# # # #         "docx": r"Saved Word:\s*(.+)$",
# # # #         "pptx": r"Saved PowerPoint:\s*(.+)$",
# # # #     }
# # # #
# # # #     for key, pat in patterns.items():
# # # #         m = re.search(pat, stdout, flags=re.MULTILINE)
# # # #         if m:
# # # #             out[key] = m.group(1).strip()
# # # #
# # # #     return out
# # # #
# # # #
# # # # def publish_run_files(saved_paths: dict) -> dict:
# # # #     """
# # # #     Copy the generated files into static/runs/<run_id>/ so Flask can serve them.
# # # #     Returns URLs (relative) you can render into HTML.
# # # #     """
# # # #     run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
# # # #     run_dir = PUBLISHED_RUNS_DIR / run_id
# # # #     run_dir.mkdir(parents=True, exist_ok=True)
# # # #
# # # #     published = {"run_id": run_id, "files": {}}
# # # #
# # # #     for ext, src in saved_paths.items():
# # # #         src_path = Path(src)
# # # #         if src_path.exists():
# # # #             dst_path = run_dir / src_path.name
# # # #             shutil.copy2(src_path, dst_path)
# # # #             published["files"][ext] = {
# # # #                 "name": dst_path.name,
# # # #                 "url": f"/static/runs/{run_id}/{dst_path.name}",
# # # #                 "path": str(dst_path),
# # # #             }
# # # #
# # # #     return published
# # # #
# # # #
# # # # @app.get("/")
# # # # def index():
# # # #     return render_template("index.html")
# # # #
# # # #
# # # # @app.post("/run")
# # # # def run_analysis():
# # # #     competitor = request.form.get("competitor", "").strip()
# # # #     baseline = request.form.get("baseline", "").strip()
# # # #     file_path = request.form.get("file", "").strip()  # optional
# # # #
# # # #     try:
# # # #         result = run_exe(competitor, baseline, file_path)
# # # #         saved = parse_saved_paths(result["stdout"])
# # # #         published = publish_run_files(saved)
# # # #
# # # #         # If we have an HTML report, we can embed it in an iframe
# # # #         html_url = published["files"].get("html", {}).get("url")
# # # #
# # # #         return render_template(
# # # #             "result.html",
# # # #             competitor=normalize_url_basic(competitor),
# # # #             baseline=normalize_url_basic(baseline) if baseline else "",
# # # #             file_path=file_path or "(auto from INI)",
# # # #             exit_code=result["exit_code"],
# # # #             cmd=result["cmd"],
# # # #             stdout_tail="\n".join((result["stdout"] or "").splitlines()[-30:]),
# # # #             stderr_tail="\n".join((result["stderr"] or "").splitlines()[-30:]),
# # # #             published=published,
# # # #             html_url=html_url,
# # # #         )
# # # #
# # # #     except Exception as e:
# # # #         return render_template("index.html", error=str(e)), 400
# # # #
# # # #
# # # # if __name__ == "__main__":
# # # #     app.run(host="127.0.0.1", port=5000, debug=True)
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# #
# # # import re
# # # import subprocess
# # # from pathlib import Path
# # # from flask import Flask, render_template, request
# # # ### install flask
# # #
# # # # {
# # # #   "baseline_raw": "door.com",
# # # #   "competitor_normalized": "https://tektelic.com",
# # # #   "competitor_raw": "https://tektelic.com",
# # # #   "file_raw": "",
# # # #   "next_step": "execute TitaniumTechnologyGapAnalysis.exe via subprocess",
# # # #   "status": "ok"
# # # # }
# # #
# # #
# # # app = Flask(__name__)
# # #
# # # # ---- EDIT THESE PATHS ----
# # # PROJECT_ROOT = Path(r"C:\Ara\Python\Titanium Inteligent Soultions")
# # #
# # # # Point this to the actual EXE produced by PyInstaller
# # # EXE_PATH = Path(
# # #     r"C:\Ara\Python\Titanium Inteligent Soultions\Titanium technology gap analysis\dist\TitaniumTechnologyGapAnalysis.exe"
# # # )
# # #
# # # # Where the web UI writes its own run log (not your script's logs)
# # # WEBUI_LOG_DIR = PROJECT_ROOT / "web_ui_logs"
# # # # --------------------------
# # #
# # #
# # # def _is_blank_baseline(s: str | None) -> bool:
# # #     if s is None:
# # #         return True
# # #     t = str(s).strip()
# # #     if not t:
# # #         return True
# # #     return t.lower() in {"n/n", "na", "n.a.", "none", "null", "-"}
# # #
# # #
# # # def normalize_domain_or_url(s: str, field_name: str) -> str:
# # #     """
# # #     Accepts:
# # #       - door.com
# # #       - https://door.com
# # #       - http://door.com
# # #
# # #     Rejects:
# # #       - door   (no dot)  -> prevents https://door host resolution failure
# # #
# # #     Returns:
# # #       - https://<domain> if no scheme was supplied
# # #       - original URL if scheme supplied
# # #     """
# # #     s = (s or "").strip()
# # #     if not s:
# # #         raise ValueError(f"{field_name} is required.")
# # #
# # #     # already has scheme
# # #     if re.match(r"^https?://", s, flags=re.IGNORECASE):
# # #         return s
# # #
# # #     # must contain dot to be a domain
# # #     if "." not in s:
# # #         raise ValueError(f"{field_name} must be a valid domain or URL (example: door.com).")
# # #
# # #     return "https://" + s
# # #
# # #
# # # @app.get("/")
# # # def index():
# # #     return render_template("index.html")
# # #
# # #
# # # @app.post("/run")
# # # def run_analysis():
# # #     competitor = request.form.get("competitor", "")
# # #     baseline = request.form.get("baseline", "")
# # #     file_path = request.form.get("file", "")
# # #
# # #     # Validate competitor
# # #     try:
# # #         competitor_norm = normalize_domain_or_url(competitor, "Competitor")
# # #     except Exception as e:
# # #         return render_template("index.html", error=str(e), competitor=competitor, baseline=baseline, file=file_path), 400
# # #
# # #     # Validate baseline (optional)
# # #     baseline_norm = ""
# # #     baseline_enabled = not _is_blank_baseline(baseline)
# # #     if baseline_enabled:
# # #         try:
# # #             baseline_norm = normalize_domain_or_url(baseline, "Baseline")
# # #         except Exception as e:
# # #             return render_template("index.html", error=str(e), competitor=competitor, baseline=baseline, file=file_path), 400
# # #
# # #     # Ensure EXE exists
# # #     if not EXE_PATH.exists():
# # #         return render_template(
# # #             "index.html",
# # #             error=f"EXE not found. Update EXE_PATH in app.py: {EXE_PATH}",
# # #             competitor=competitor,
# # #             baseline=baseline,
# # #             file=file_path
# # #         ), 500
# # #
# # #     # Build command
# # #     cmd = [str(EXE_PATH), "--competitor", competitor_norm]
# # #
# # #     # pass baseline only if enabled
# # #     if baseline_enabled:
# # #         cmd += ["--baseline", baseline_norm]
# # #
# # #     # pass file only if user provided (otherwise your script auto-picks from INI)
# # #     file_path = (file_path or "").strip()
# # #     if file_path:
# # #         cmd += ["--file", file_path]
# # #
# # #     # Run and capture logs
# # #     WEBUI_LOG_DIR.mkdir(parents=True, exist_ok=True)
# # #     log_path = WEBUI_LOG_DIR / "last_run.log"
# # #
# # #     try:
# # #         with log_path.open("w", encoding="utf-8") as logf:
# # #             logf.write("COMMAND:\n" + " ".join(cmd) + "\n\n")
# # #             proc = subprocess.run(
# # #                 cmd,
# # #                 cwd=str(EXE_PATH.parent),
# # #                 stdout=logf,
# # #                 stderr=subprocess.STDOUT,
# # #                 text=True,
# # #                 check=False
# # #             )
# # #         exit_code = proc.returncode
# # #     except Exception as e:
# # #         return render_template(
# # #             "index.html",
# # #             error=f"Failed to run EXE: {e}",
# # #             competitor=competitor,
# # #             baseline=baseline,
# # #             file=file_path
# # #         ), 500
# # #
# # #     # Show last lines of output in browser
# # #     try:
# # #         lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
# # #         tail = "\n".join(lines[-120:])
# # #     except Exception:
# # #         tail = "(Could not read web UI log.)"
# # #
# # #     return render_template(
# # #         "result.html",
# # #         competitor=competitor_norm,
# # #         baseline=(baseline_norm if baseline_enabled else "(disabled)"),
# # #         file=(file_path if file_path else "(auto from INI)"),
# # #         exit_code=exit_code,
# # #         log_path=str(log_path),
# # #         log_tail=tail
# # #     )
# # #
# # #
# # # if __name__ == "__main__":
# # #     app.run(host="127.0.0.1", port=5000, debug=True)
