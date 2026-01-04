## routes.py
from __future__ import annotations

from pathlib import Path
from typing import Dict
from types import SimpleNamespace  # <-- ADDED

from flask import Blueprint, abort, current_app, render_template, request, send_file

from tga_web.config import IniConfig
from tga_web.domain.models import AnalysisResult, RunOutputs

PRESET_INSTRUCTIONS = {
    "scoring": (
        "Include a scoring table comparing baseline vs competitor on a 1–5 scale.\n"
        "Add brief justification per criterion.\n"
        "Summarize the top three differentiators based on the scores."
    ),
    "executive": (
        "Write for an executive audience.\n"
        "Start with a one-page executive summary.\n"
        "Focus on business impact, cost, and risk. Avoid jargon."
    ),
    "technical": (
        "Provide a detailed technical comparison.\n"
        "Include architecture, integration complexity, scalability, and security.\n"
        "Assume the reader is a technical architect."
    ),
    "evidence_strict": (
        "Base conclusions strictly on the provided documents and websites.\n"
        "If information is missing, state 'insufficient information'.\n"
        "Do not infer capabilities without evidence."
    ),
    "slide": (
        "Format the output to be slide-ready.\n"
        "Use short bullet points; max 5 bullets per section."
    ),
    "risk": (
        "Emphasize compliance, security, and regulatory considerations.\n"
        "Highlight risks, gaps, and mitigations.\n"
        "Include operational resilience."
    ),
}


def _safe_int(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() else None


def _link_for(run_id: str, p: Path | None) -> str | None:
    if not p:
        return None
    return f"/download/{run_id}/{p.name}"


def create_blueprint(analysis_service, preset_repo) -> Blueprint:
    bp = Blueprint("web", __name__)
    runs: Dict[str, Path] = {}

    def load_dropdown_data():
        """
        Returns data shaped to match the template:

        - presets: list of objects with .id and .name
          (repo objects appear to use preset_id / preset_display_name)
        - instruction_presets: list[str]
        """
        presets_raw = preset_repo.get_active_presets() or []
        presets: list[SimpleNamespace] = []

        for p in presets_raw:
            # Your repo objects (per your logging) use preset_id / preset_display_name
            pid = getattr(p, "preset_id", None)
            pname = getattr(p, "preset_display_name", None)

            # Fallback if repo already returns id/name
            if pid is None:
                pid = getattr(p, "id", None)
            if pname is None:
                pname = getattr(p, "name", None)

            if pid is None or pname is None:
                continue

            presets.append(SimpleNamespace(id=pid, name=pname))

        raw_instr = preset_repo.get_distinct_instruction_presets() or []
        instruction_presets: list[str] = []
        for k in raw_instr:
            if isinstance(k, str):
                val = k
            else:
                # try common row/object attribute names
                val = getattr(k, "instruction_preset", None) or getattr(k, "name", None) or str(k)
            val = (val or "").strip()
            if val:
                instruction_presets.append(val)

        # Deduplicate preserving order
        seen = set()
        instruction_presets = [x for x in instruction_presets if not (x in seen or seen.add(x))]

        return presets, instruction_presets

    @bp.get("/")
    def index():
        settings = IniConfig.from_env_or_default().load_settings()

        # Read selected preset_id from query string (FIXED: not inside any except)
        preset_id = _safe_int(request.args.get("preset_id"))

        # Load dropdowns
        try:
            presets, instruction_presets = load_dropdown_data()
        except Exception as e:
            current_app.logger.exception("Failed to load dropdown data from SQL Server")
            return render_template(
                "index.html",
                presets=[],
                instruction_presets=[],  # <-- ensure template has it even on error
                preset_id=preset_id,
                competitor="",
                baseline="",
                file="",
                instruction_preset="",
                extra_instructions=getattr(settings, "extra_instructions", "") or "",
                error=f"Failed to load dropdown data from SQL Server: {e}",
            )

        current_app.logger.info("Presets loaded: %d", len(presets))
        current_app.logger.info("Instruction presets loaded: %d", len(instruction_presets))

        # Defaults (IMPORTANT: include instruction_presets for template)
        page_model = dict(
            presets=presets,
            instruction_presets=instruction_presets,  # <-- ADDED (this is why your 2nd dropdown was empty)
            preset_id=preset_id,
            competitor="",
            baseline="",
            file="",
            instruction_preset="",
            extra_instructions=getattr(settings, "extra_instructions", "") or "",
            error=None,
        )

        # If preset selected, fetch it and prefill values
        if preset_id is not None:
            p = preset_repo.get_preset(preset_id)
            if p is None:
                page_model["error"] = f"Preset id {preset_id} not found or inactive."
            else:
                page_model.update(
                    competitor=(p.competitor or "").strip(),
                    baseline=(p.baseline or "").strip(),
                    file=(getattr(p, "source_file_path", "") or "").strip(),
                    instruction_preset=(p.instruction_preset or "").strip(),
                    extra_instructions=(p.extra_instructions or getattr(settings, "extra_instructions", "") or ""),
                )

        return render_template("index.html", **page_model)

    @bp.post("/run")
    def run_analysis():
        settings = IniConfig.from_env_or_default().load_settings()

        preset_id = _safe_int(request.form.get("preset_id"))
        preset = preset_repo.get_preset(preset_id) if preset_id else None

        competitor_raw = (request.form.get("competitor") or "").strip()
        baseline_raw = (request.form.get("baseline") or "").strip()

        file_raw = (request.form.get("file") or "").strip()
        if not file_raw:
            file_raw = (getattr(preset, "source_file_path", "") or "").strip()

        if preset is not None:
            p = preset_repo.get_preset(preset_id)
            current_app.logger.info("preset loaded=%r", p is not None)
            current_app.logger.info("preset.instruction_preset=%r", getattr(p, "instruction_preset", None))

            if not competitor_raw:
                competitor_raw = (preset.competitor or "").strip()
            if not baseline_raw:
                baseline_raw = (preset.baseline or "").strip()
            if not file_raw:
                file_raw = (getattr(preset, "source_file_path", "") or "").strip()

        preset_key = (request.form.get("instruction_preset") or "").strip()
        free_text = (request.form.get("extra_instructions") or "").strip()

        if preset is not None:
            if not preset_key:
                preset_key = (preset.instruction_preset or "").strip()
            if not free_text:
                free_text = (preset.extra_instructions or "").strip()

        preset_text = PRESET_INSTRUCTIONS.get(preset_key, "")
        final_extra = "\n\n".join([t for t in (preset_text, free_text) if t]).strip()
        if not final_extra:
            final_extra = (getattr(settings, "extra_instructions", "") or "").strip()

        result: AnalysisResult = analysis_service.run(
            competitor_raw,
            baseline_raw,
            file_raw,
            extra_instructions=final_extra,
            instruction_preset=preset_key,
        )

        if result.run_dir:
            runs[result.run_id] = Path(result.run_dir)

        outputs: RunOutputs | None = result.outputs
        generated = {
            "html": _link_for(result.run_id, outputs.html if outputs else None),
            "docx": _link_for(result.run_id, outputs.docx if outputs else None),
            "pptx": _link_for(result.run_id, outputs.pptx if outputs else None),
            "md": _link_for(result.run_id, outputs.md if outputs else None),
        }

        code = 200 if result.status == "ok" else 500
        current_app.logger.info("Run %s status=%s exit=%s", result.run_id, result.status, result.exit_code)

        return render_template(
            "result.html",
            status=result.status,
            competitor=result.competitor,
            baseline=result.baseline,
            generated_at=result.generated_at,
            duration_seconds=result.duration_seconds,
            exit_code=result.exit_code,
            generated=generated,
            stdout_tail=result.stdout_tail,
            stderr_tail=result.stderr_tail,
            run_dir=result.run_dir,
        ), code

    @bp.get("/download/<run_id>/<filename>")
    def download(run_id: str, filename: str):
        run_dir = runs.get(run_id)
        if not run_dir:
            abort(404)

        full = (run_dir / filename).resolve()
        if run_dir.resolve() not in full.parents:
            abort(403)
        if not full.exists() or not full.is_file():
            abort(404)

        as_attach = full.suffix.lower() not in {".html"}
        return send_file(full, as_attachment=as_attach)

    return bp


# ## routes.py
#
# from __future__ import annotations
#
# from pathlib import Path
# from typing import Dict
#
# from flask import Blueprint, abort, current_app, render_template, request, send_file
#
# from tga_web.config import IniConfig
# from tga_web.domain.models import AnalysisResult, RunOutputs
#
# PRESET_INSTRUCTIONS = {
#     "scoring": (
#         "Include a scoring table comparing baseline vs competitor on a 1–5 scale.\n"
#         "Add brief justification per criterion.\n"
#         "Summarize the top three differentiators based on the scores."
#     ),
#     "executive": (
#         "Write for an executive audience.\n"
#         "Start with a one-page executive summary.\n"
#         "Focus on business impact, cost, and risk. Avoid jargon."
#     ),
#     "technical": (
#         "Provide a detailed technical comparison.\n"
#         "Include architecture, integration complexity, scalability, and security.\n"
#         "Assume the reader is a technical architect."
#     ),
#     "evidence_strict": (
#         "Base conclusions strictly on the provided documents and websites.\n"
#         "If information is missing, state 'insufficient information'.\n"
#         "Do not infer capabilities without evidence."
#     ),
#     "slide": (
#         "Format the output to be slide-ready.\n"
#         "Use short bullet points; max 5 bullets per section."
#     ),
#     "risk": (
#         "Emphasize compliance, security, and regulatory considerations.\n"
#         "Highlight risks, gaps, and mitigations.\n"
#         "Include operational resilience."
#     ),
# }
#
#
# def _safe_int(raw: str | None) -> int | None:
#     raw = (raw or "").strip()
#     return int(raw) if raw.isdigit() else None
#
#
# def _link_for(run_id: str, p: Path | None) -> str | None:
#     if not p:
#         return None
#     return f"/download/{run_id}/{p.name}"
#
#
# def create_blueprint(analysis_service, preset_repo) -> Blueprint:
#     bp = Blueprint("web", __name__)
#     runs: Dict[str, Path] = {}
#
#     @bp.get("/")
#     def index():
#         settings = IniConfig.from_env_or_default().load_settings()
#
#         # 1) Load presets for the main preset dropdown
#         try:
#             presets = preset_repo.get_active_presets()
#         except Exception as e:
#             current_app.logger.exception("Failed to load presets from SQL Server")
#
#             return render_template(
#                 "index.html",
#                 presets=[],
#                 preset_id=None,
#                 competitor="",
#                 baseline="",
#                 file="",
#                 instruction_preset="",
#                 extra_instructions=getattr(settings, "extra_instructions", "") or "",
#                 error=f"Failed to load presets from SQL Server: {e}",
#             )
#
#         current_app.logger.info("Presets loaded: %d", len(presets))
#
#         # 2) Load DISTINCT instruction presets for the instruction dropdown (DB-driven)
#         try:
#             instruction_presets = preset_repo.get_distinct_instruction_presets()
#         except Exception as e:
#             current_app.logger.exception("Failed to load instruction presets from SQL Server")
#             instruction_presets = []  # keep the page working
#
#         # 3) Read selected preset_id from query string
#             preset_id = _safe_int(request.args.get("preset_id"))
#
#         if presets:
#             p0 = presets[0]
#             current_app.logger.info(
#                 "Preset[0]: id=%s display=%s competitor=%s",
#                 getattr(p0, "preset_id", None),
#                 getattr(p0, "preset_display_name", None),
#                 getattr(p0, "competitor", None),
#             )
#
#         preset_id = _safe_int(request.args.get("preset_id"))
#
#         # 4) Defaults
#         page_model = dict(
#             presets=presets,
#             preset_id=preset_id,
#             competitor="",
#             baseline="",
#             file="",
#             instruction_preset="",
#             extra_instructions=getattr(settings, "extra_instructions", "") or "",
#             error=None,
#         )
#
#         # 5) If preset selected, fetch it and prefill values
#         if preset_id is not None:
#             p = preset_repo.get_preset(preset_id)
#             if p is None:
#                 page_model["error"] = f"Preset id {preset_id} not found or inactive."
#             else:
#                 page_model.update(
#                     competitor=(p.competitor or "").strip(),
#                     baseline=(p.baseline or "").strip(),
#                     file=(getattr(p, "source_file_path", "") or "").strip(),
#                     instruction_preset=(p.instruction_preset or "").strip(),
#                     extra_instructions=(p.extra_instructions or getattr(settings, "extra_instructions", "") or ""),
#                 )
#
#         return render_template("index.html", **page_model)
#
#     @bp.post("/run")
#     def run_analysis():
#         settings = IniConfig.from_env_or_default().load_settings()
#
#         preset_id = _safe_int(request.form.get("preset_id"))
#         preset = preset_repo.get_preset(preset_id) if preset_id else None
#
#         competitor_raw = (request.form.get("competitor") or "").strip()
#         baseline_raw = (request.form.get("baseline") or "").strip()
#
#         file_raw = (request.form.get("file") or "").strip()
#         if not file_raw:
#             file_raw = (getattr(preset, "source_file_path", "") or "").strip()
#
#
#         if preset is not None:
#
#             p = preset_repo.get_preset(preset_id)
#             current_app.logger.info("preset loaded=%r", p is not None)
#             current_app.logger.info("preset.instruction_preset=%r", getattr(p, "instruction_preset", None))
#
#             if not competitor_raw:
#                 competitor_raw = (preset.competitor or "").strip()
#             if not baseline_raw:
#                 baseline_raw = (preset.baseline or "").strip()
#             if not file_raw:
#                 file_raw = (getattr(preset, "source_file_path", "") or "").strip()
#
#         preset_key = (request.form.get("instruction_preset") or "").strip()
#         free_text = (request.form.get("extra_instructions") or "").strip()
#
#         if preset is not None:
#             if not preset_key:
#                 preset_key = (preset.instruction_preset or "").strip()
#             if not free_text:
#                 free_text = (preset.extra_instructions or "").strip()
#
#         preset_text = PRESET_INSTRUCTIONS.get(preset_key, "")
#         final_extra = "\n\n".join([t for t in (preset_text, free_text) if t]).strip()
#         if not final_extra:
#             final_extra = (getattr(settings, "extra_instructions", "") or "").strip()
#
#         result: AnalysisResult = analysis_service.run(
#             competitor_raw,
#             baseline_raw,
#             file_raw,
#             extra_instructions=final_extra,
#             instruction_preset=preset_key,
#         )
#
#         if result.run_dir:
#             runs[result.run_id] = Path(result.run_dir)
#
#         outputs: RunOutputs | None = result.outputs
#         generated = {
#             "html": _link_for(result.run_id, outputs.html if outputs else None),
#             "docx": _link_for(result.run_id, outputs.docx if outputs else None),
#             "pptx": _link_for(result.run_id, outputs.pptx if outputs else None),
#             "md": _link_for(result.run_id, outputs.md if outputs else None),
#         }
#
#         code = 200 if result.status == "ok" else 500
#         current_app.logger.info("Run %s status=%s exit=%s", result.run_id, result.status, result.exit_code)
#
#         return render_template(
#             "result.html",
#             status=result.status,
#             competitor=result.competitor,
#             baseline=result.baseline,
#             generated_at=result.generated_at,
#             duration_seconds=result.duration_seconds,
#             exit_code=result.exit_code,
#             generated=generated,
#             stdout_tail=result.stdout_tail,
#             stderr_tail=result.stderr_tail,
#             run_dir=result.run_dir,
#         ), code
#
#     @bp.get("/download/<run_id>/<filename>")
#     def download(run_id: str, filename: str):
#         run_dir = runs.get(run_id)
#         if not run_dir:
#             abort(404)
#
#         full = (run_dir / filename).resolve()
#         if run_dir.resolve() not in full.parents:
#             abort(403)
#         if not full.exists() or not full.is_file():
#             abort(404)
#
#         as_attach = full.suffix.lower() not in {".html"}
#         return send_file(full, as_attachment=as_attach)
#
#     return bp
#
