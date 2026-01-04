# CFG = configparser.ConfigParser()import os
# import re
# import subprocess
# from configparser import ConfigParser
# from datetime import datetime
# from pathlib import Path
# from typing import Optional
#
# from flask import Flask, render_template, request, url_for, send_from_directory, abort
# # -----------------------------
# # Config loading
# # -----------------------------
# INI_DEFAULT_NAME = "TitaniumTechnologyGapAnalysisAppRef.ini"
#
#
# def load_config() -> ConfigParser:
#     """
#     Loads TitaniumTechnologyGapAnalysisApp.ini from the same directory as this script
#     by default. Allows override via env var APP_INI.
#     """
#     cfg = ConfigParser()
#
#     ini_path = Path(os.getenv("APP_INI", Path(__file__).with_name(INI_DEFAULT_NAME)))
#     read_ok = cfg.read(ini_path)
#
#     if not read_ok:
#         raise FileNotFoundError(f"INI file not found or unreadable: {ini_path}")
#
#     return cfg
#
#
# CFG = load_config()
#
# # -----------------------------
# # Config values
# # -----------------------------
# REPORTS_BASE = Path(CFG.get("paths", "reports_base"))
# EXE_PATH = Path(CFG.get("paths", "exe_path"))
#
# TIMEOUT_SECONDS = CFG.getint("execution", "timeout_seconds", fallback=60 * 30)
#
# DEFAULT_SCHEME = CFG.get("url_normalization", "default_scheme", fallback="https").strip() or "https"
# GUESS_COM_IF_NO_DOT = CFG.getboolean("url_normalization", "guess_com_if_no_dot", fallback=True)
#
# NO_GUESS_HOSTS = {
#     h.strip().lower()
#     for h in CFG.get("url_normalization", "no_guess_hosts", fallback="localhost").split(",")
#     if h.strip()
# }
#
# FLASK_HOST = CFG.get("flask", "host", fallback="127.0.0.1")
# FLASK_PORT = CFG.getint("flask", "port", fallback=5000)
# FLASK_DEBUG = CFG.getboolean("flask", "debug", fallback=True)
#
# # -----------------------------
# # Validation (fail fast)
# # -----------------------------
# if not EXE_PATH.exists():
#     raise FileNotFoundError(f"EXE not found: {EXE_PATH}")
#
# if not REPORTS_BASE.exists():
#     # If you want to auto-create, uncomment:
#     # REPORTS_BASE.mkdir(parents=True, exist_ok=True)
#     raise FileNotFoundError(f"Reports base folder not found: {REPORTS_BASE}")
#
# # -----------------------------
# # Flask app
# # -----------------------------
# app = Flask(__name__)
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
#       - door          (guesses .com depending on INI)
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
#     # Guess .com if no dot (except configured exclusions)
#     if GUESS_COM_IF_NO_DOT and "." not in host and host.lower() not in NO_GUESS_HOSTS:
#         host = host + ".com"
#
#     return f"{DEFAULT_SCHEME}://" + host + rest
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
#     return send_from_directory(full.parent, full.name, as_attachment=False)
#
#
# # -----------------------------
# # Pages
# # -----------------------------
# @app.get("/")
# def index():
#     return render_template("index.html")
# @app.post("/run")
# def run_analysis():
#     competitor_raw = request.form.get("competitor", "").strip()
#     baseline_raw = request.form.get("baseline", "").strip()   # FIXED
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
#     if baseline_raw != "":  # user touched the field (including blank)
#         # Option A (recommended if you want blank field to DISABLE baseline even if INI has one):
#         # Always pass --baseline; empty means disable in your EXE argparse (nargs="?", const="")
#         cmd += ["--baseline", baseline_norm]  # baseline_norm may be ""
#     # If you want empty field to mean "use INI fallback", then use instead:
#     # if baseline_norm:
#     #     cmd += ["--baseline", baseline_norm]
#
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
#     # Debug: confirm what is being executed
#     app.logger.info("Running command: %r", cmd)
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
# if __name__ == "__main__":
#     # Local dev only
#     app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
#
#
# # -------------------------------------------------------------------
# # Main (CORRECTED)
# # -------------------------------------------------------------------