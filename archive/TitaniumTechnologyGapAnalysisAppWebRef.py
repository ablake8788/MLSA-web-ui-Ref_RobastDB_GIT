
import os
import re
import subprocess
from configparser import ConfigParser
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

from flask import Flask, render_template, request, send_file, abort


INI_DEFAULT_NAME = "TitaniumTechnologyGapAnalysisAppWebRef.ini"

# -----------------------------
# Config loading
# -----------------------------
def load_cfg() -> tuple[ConfigParser, Path]:
    cfg = ConfigParser()
    ini_raw = (os.getenv("APP_INI") or "").strip()
    ini_path = Path(ini_raw) if ini_raw else (Path(__file__).resolve().parent / INI_DEFAULT_NAME)

    read_ok = cfg.read(str(ini_path), encoding="utf-8-sig")
    if not read_ok:
        raise FileNotFoundError(f"INI file not found or unreadable: {ini_path}")

    print("Loaded INI:", ini_path)
    print("Sections:", cfg.sections())
    return cfg, ini_path


CFG, INI_PATH = load_cfg()


def cfg_path(section: str, key: str) -> Path:
    # Try requested section, then fallback between "path" and "paths"
    sections_to_try = [section]
    if section == "paths":
        sections_to_try.append("path")
    if section == "path":
        sections_to_try.append("paths")

    for sec in sections_to_try:
        if not CFG.has_section(sec):
            continue
        raw = (CFG.get(sec, key, fallback="") or "").strip()
        if raw:
            raw = os.path.expandvars(os.path.expanduser(raw))
            return Path(raw).resolve()

    raise FileNotFoundError(f"Missing INI value for {key} in sections: {sections_to_try}")


# -----------------------------
# Config values
# -----------------------------
EXE_PATH = cfg_path("paths", "exe_path")
REPORTS_BASE = cfg_path("paths", "reports_base")

TIMEOUT_SECONDS = CFG.getint("execution", "timeout_seconds", fallback=1800)

DEFAULT_SCHEME = (CFG.get("url_normalization", "default_scheme", fallback="https") or "").strip() or "https"
GUESS_COM_IF_NO_DOT = CFG.getboolean("url_normalization", "guess_com_if_no_dot", fallback=True)
NO_GUESS_HOSTS = {
    h.strip().lower()
    for h in (CFG.get("url_normalization", "no_guess_hosts", fallback="localhost") or "").split(",")
    if h.strip()
}

FLASK_HOST = (CFG.get("flask", "host", fallback="127.0.0.1") or "").strip() or "127.0.0.1"
FLASK_PORT = CFG.getint("flask", "port", fallback=5000)
FLASK_DEBUG = CFG.getboolean("flask", "debug", fallback=True)

if not EXE_PATH.exists():
    raise FileNotFoundError(f"EXE not found: {EXE_PATH}")

# Ensure reports folder exists
REPORTS_BASE.mkdir(parents=True, exist_ok=True)

print("EXE_PATH     =", EXE_PATH)
print("REPORTS_BASE =", REPORTS_BASE)


# -----------------------------
# Flask app
# -----------------------------
app = Flask(__name__)
RUNS: Dict[str, Path] = {}


# -----------------------------
# URL normalization
# -----------------------------
def normalize_url_guess_com(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""

    if re.match(r"^https?://", s, flags=re.IGNORECASE):
        return s

    parts = s.split("/", 1)
    host = parts[0].strip()
    rest = ("/" + parts[1]) if len(parts) > 1 else ""

    if GUESS_COM_IF_NO_DOT and "." not in host and host.lower() not in NO_GUESS_HOSTS:
        host = host + ".com"

    return f"{DEFAULT_SCHEME}://" + host + rest


# -----------------------------
# Run dir detection
# -----------------------------
def newest_run_dir_in(base: Path) -> Optional[Path]:
    if not base.exists():
        return None
    candidates = [p for p in base.iterdir() if p.is_dir() and p.name.startswith("comparison_report_")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_newest_run_dir() -> Optional[Path]:
    # Prefer REPORTS_BASE, but fallback to EXE folder if EXE still writes there
    a = newest_run_dir_in(REPORTS_BASE)
    b = newest_run_dir_in(EXE_PATH.parent)
    if a and b:
        return a if a.stat().st_mtime >= b.stat().st_mtime else b
    return a or b


def pick_outputs(run_dir: Path) -> Dict[str, Optional[Path]]:
    return {
        "html": next(run_dir.glob("*.html"), None),
        "docx": next(run_dir.glob("*.docx"), None),
        "pptx": next(run_dir.glob("*.pptx"), None),
        "md": next(run_dir.glob("*.md"), None),
    }


# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def index():
    return render_template("index.html")


@app.post("/run")
def run_analysis():
    competitor_raw = request.form.get("competitor", "").strip()
    baseline_raw = request.form.get("baseline", "").strip()
    file_raw = request.form.get("file", "").strip()

    competitor = normalize_url_guess_com(competitor_raw)
    baseline = normalize_url_guess_com(baseline_raw) if baseline_raw else ""

    if not competitor:
        return render_template("index.html", error="Competitor is required."), 400

    # Always pass --baseline so blank disables baseline in your EXE argparse
    cmd = [str(EXE_PATH), "--competitor", competitor, "--baseline", baseline]
    if file_raw:
        cmd += ["--file", file_raw]

    started = datetime.now()
    app.logger.info("Running: %r", cmd)

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
    duration_seconds = int((finished - started).total_seconds())
    generated_at = finished.strftime("%Y-%m-%d %H:%M:%S")

    run_dir = find_newest_run_dir()
    outputs = pick_outputs(run_dir) if run_dir else {"html": None, "docx": None, "pptx": None, "md": None}

    run_id = finished.strftime("%Y%m%d_%H%M%S")
    if run_dir:
        RUNS[run_id] = run_dir

    def link_for(p: Optional[Path]) -> Optional[str]:
        if not p:
            return None
        return f"/download/{run_id}/{p.name}"

    generated = {
        "html": link_for(outputs.get("html")),
        "docx": link_for(outputs.get("docx")),
        "pptx": link_for(outputs.get("pptx")),
        "md": link_for(outputs.get("md")),
    }

    stdout_tail = "\n".join((proc.stdout or "").splitlines()[-60:])
    stderr_tail = "\n".join((proc.stderr or "").splitlines()[-60:])

    status = "ok" if proc.returncode == 0 else "failed"
    code = 200 if status == "ok" else 500

    return render_template(
        "result.html",
        status=status,
        competitor=competitor,
        baseline=baseline,
        generated_at=generated_at,
        duration_seconds=duration_seconds,
        exit_code=proc.returncode,
        generated=generated,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        run_dir=str(run_dir) if run_dir else "",
    ), code


@app.get("/download/<run_id>/<filename>")
def download(run_id: str, filename: str):
    run_dir = RUNS.get(run_id)
    if not run_dir:
        abort(404)

    full = (run_dir / filename).resolve()
    if run_dir.resolve() not in full.parents:
        abort(403)
    if not full.exists() or not full.is_file():
        abort(404)

    as_attach = full.suffix.lower() not in {".html"}
    return send_file(full, as_attachment=as_attach)


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)

########################################