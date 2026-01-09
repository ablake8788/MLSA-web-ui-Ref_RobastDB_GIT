from __future__ import annotations

from flask import Flask

from tga_web.config.ini_config import IniConfig
from tga_web.repositories.run_repository import RunRepository
from tga_web.services.analysis_service import AnalysisService
from tga_web.services.url_normalization import GuessComUrlNormalizer
from tga_web.web.routes import create_blueprint

from tga_web.adapters.sqlserver_presets import SqlServerPresetRepository


def create_app() -> Flask:
    ini = IniConfig.from_env_or_default()
    settings = ini.load_settings()

    url_norm = GuessComUrlNormalizer(
        default_scheme=settings.default_scheme,
        guess_com_if_no_dot=settings.guess_com_if_no_dot,
        no_guess_hosts=settings.no_guess_hosts,
    )

    run_repo = RunRepository(
        reports_base=settings.reports_base,
        exe_dir=settings.exe_path.parent,
    )

    analysis_service = AnalysisService(
        exe_path=settings.exe_path,
        timeout_seconds=settings.timeout_seconds,
        url_normalizer=url_norm,
        run_repo=run_repo,
    )

    preset_repo = SqlServerPresetRepository(
        ini_path=str(getattr(ini, "_ini_path", "MLSA_GapAnalysisRefDB.ini")),
        table_name="dbo.GapAnalysisPresets",
    )

    app = Flask(__name__)
    app.register_blueprint(create_blueprint(analysis_service, preset_repo))

    app.config["HOST"] = settings.flask_host
    app.config["PORT"] = settings.flask_port
    app.config["DEBUG"] = settings.flask_debug

    return app

# architectural design comments for this codebase, including the key design patterns embodied by the structure
#
# #############################################
# # # composition root (wiring)
# # project_root/
# #   TitaniumTechnologyGapAnalysisRef.ini
# #   tga_cli/
# #     __init__.py
# #     __main__.py                 # python -m tga_cli
# #     app_factory.py              # composition root (wiring)
# #
# #     config/
# #       __init__.py
# #       ini_config.py             # load INI + normalize paths -> AppSettings
# #
# #     domain/
# #       __init__.py
# #       models.py                 # dataclasses: Inputs, Outputs, RunContext, Result
# #       errors.py                 # domain exceptions (ValidationError, FatalError, etc.)
# #
# #     cli/
# #       __init__.py
# #       args.py                   # argparse only
# #       controller.py             # calls service, handles exit codes/logging
# #
# #     logging/
# #       __init__.py
# #       setup.py                  # setup_logging + resource_path
# #
# #     services/
# #       __init__.py
# #       analysis_service.py       # main workflow orchestration
# #       baseline_policy.py        # baseline precedence rules (isolated)
# #       prompt_builder.py         # build_prompt only
# #       url_normalizer.py         # normalize_url + validate_http_url
# #
# #     ports/
# #       __init__.py
# #       llm.py                    # interface for LLM client
# #       fetcher.py                # interface for website fetch
# #       readers.py                # interface for document reader
# #       renderers.py              # interface for report renderers
# #       emailer.py                # interface for email sender
# #
# #     adapters/s
# #       __init__.py
# #       llm_openai.py             # OpenAI adapter
# #       fetch_requests.py         # requests + BS4 (+ readability) adapter
# #       readers_pdf.py            # pypdf + pdf2image + tesseract adapter
# #       readers_docx.py
# #       readers_image.py
# #       email_smtp.py             # smtplib adapter
# #
# #     renderers/
# #       __init__.py
# #       markdown_normalizer.py    # normalize_report_markdown
# #       html_renderer.py          # markdown + CSS template
# #       docx_renderer.py          # markdown_to_docx
# #       pptx_renderer.py          # markdown_to_pptx_table_style
# #
# #     repositories/
# #       __init__.py
# #       report_repository.py      # ensure_reports_dir / ensure_run_dir / file naming
# #
# #     utils/
# #       __init__.py
# #       text.py                   # truncate, safe_slug, competitor_slug_from_url
# #
# #   tests/
# #     test_url_normalizer.py
# #     test_baseline_policy.py
# #     test_prompt_builder.py
# #     test_report_repository.py
# #     test_analysis_service_unit.py
#
#
# #############################################
#
# # CLI entrypoint
# #
# # tga_cli/__main__.py starts the app via app_factory.py.
# #
# # Controller triggers the workflow
# #
# # cli/controller.py receives parsed args (from cli/args.py) and calls the main orchestration:
# #
# # services/analysis_service.py
# #
# # Inputs are gathered and normalized (still no ChatGPT call)
# #
# # config/ini_config.py loads and normalizes config into AppSettings.
# #
# # services/url_normalizer.py normalizes/validates URLs.
# #
# # services/baseline_policy.py applies precedence rules for which baseline to use.
# #
# # adapters/fetch_requests.py fetches website content if needed.
# #
# # adapters/readers_*.py read documents (PDF/DOCX/images).
# #
# # The comparison prompt is assembled
# #
# # services/prompt_builder.py constructs the final prompt (the actual “comparison request” text).
# #
# # This is where it is submitted to ChatGPT
# #
# # Inside services/analysis_service.py, after the prompt is built, the service calls the LLM via the port:
# #
# # ports/llm.py (interface)
# #
# # implemented by adapters/llm_openai.py (OpenAI / ChatGPT adapter)
# #
# # So the specific point is:
# #
# # services/analysis_service.py → calls ports.llm (implemented by adapters/llm_openai.py) with the prompt produced by services/prompt_builder.py.
# #
# # If you want to identify the exact line(s), look for something shaped like:
# #
# # prompt = prompt_builder.build_prompt(...)
# #
# # llm_response = llm_client.generate(...) / llm_client.complete(...) / llm_client.chat(...)
# #
# # and that llm_client is created/wired in app_factory.py.



