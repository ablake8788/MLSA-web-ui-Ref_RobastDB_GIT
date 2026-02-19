from tga_web.app_factory import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=app.config["DEBUG"])


###########################################
# architectural design comments for this codebase,
# including the key design patterns embodied by the structure
#
# *********************************************
# Key design patterns used
# •	Application Factory: create_app() builds the app and dependencies.
# •	Dependency Injection (manual): dependencies are passed into routes and service constructors.
# •	Service Layer: AnalysisService encapsulates the use case.
# •	Repository: RunRepository encapsulates filesystem queries.
# •	Strategy: UrlNormalizer allows you to swap normalization logic.
## *********************************************
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

#############################
#
# PS C:\Ara\Python\MLSA gap analysis Ref\MLSA_web_ui Ref_RobastDB_GIT>
# 	python -m tga_web

# Key design patterns used
# •	Application Factory: create_app() builds the app and dependencies.
# •	Dependency Injection (manual): dependencies are passed into routes and service constructors.
# •	Service Layer: AnalysisService encapsulates the use case.
# •	Repository: RunRepository encapsulates filesystem queries.
# •	Strategy: UrlNormalizer allows you to swap normalization logic.
######################################################################
# High-level architecture
# •	Goal: Thin web layer, business logic in services, filesystem interactions in repositories, configuration isolated, domain models centralized.
# •	Presentation (Flask)
#    |
#    v
# Application / Service Layer
#    |
#    v
# Infrastructure (Repository + OS/Subprocess)
#    |
#    v
# External System (TitaniumTechnologyGapAnalysisRef.exe + filesystem outputs)
# ________________________________________
# Directory layout and responsibilities
# •	tga_web/app_factory.py — Application Factory
# •	Pattern: Application Factory + Composition Root
# Role: Creates the Flask app, loads config, wires dependencies (service, repository, strategies), registers routes.
# •	Owns:
# •	constructing IniConfig
# •	AppSettings
# •	instantiating UrlNormalizer, RunRepository, AnalysisService
# •	app.register_blueprint(...)
# •	________________________________________
# 2) tga_web/config/ — Configuration layer
# •	Files:
# •	ini_config.py
# •	__init__.py
# •	Pattern: Adapter / Configuration Provider
# Role: Reads INI, resolves paths, returns a strongly typed AppSettings.
# •	Owns:
# •	INI reading
# •	env var override (APP_INI)
# path resolution and validation (EXE exists, reports folder exists)
# ________________________________________
# 3) tga_web/domain/ — Domain models
# •	Files:
# •	models.py
# •	__init__.py
# •	Pattern: Domain Model
# Role: Pure data structures (dataclass) describing results and outputs.
# •	Contains:
# •	RunOutputs
# •	AnalysisResult
# •	Important: No Flask, no filesystem code, no subprocess code.
# •	________________________________________
# 4) tga_web/services/ — Service layer (business logic)
# •	Files:
# •	analysis_service.py
# •	url_normalization.py
# •	__init__.py
# •	Patterns:
# •	Service Layer / Use Case
# •	Strategy (UrlNormalizer)
# •	Roles:
# •	AnalysisService: orchestrates one “run analysis” operation:
# •	normalize inputs
# •	build EXE command
# •	execute EXE via subprocess.run
# •	ask repository for newest run folder and outputs
# •	return AnalysisResult
# •	UrlNormalizer + GuessComUrlNormalizer:
# •	encapsulates URL normalization logic so it is swappable/testable
# •	________________________________________
# 5) tga_web/repositories/ — Repository layer (filesystem discovery)
# •	Files:
# •	run_repository.py
# •	__init__.py
# •	Pattern: Repository
# Role: Encapsulates how you locate run directories and output files.
# •	Owns:
# •	scanning reports_base and exe_dir
# •	choosing “newest comparison_report_*”
# •	selecting *.html, *.docx, *.pptx, *.md
# ________________________________________
# 6) tga_web/web/ — Web / Controller layer
# •	Files:
# •	routes.py
# •	__init__.py
# •	Pattern: MVC Controller (Flask blueprint)
# Role: HTTP endpoints only. No business logic.
# •	Owns:
# •	reading form input
# •	calling AnalysisService.run(...)
# •	building download links
# •	rendering templates
# •	download route validation (path traversal protection)
# ________________________________________
# 7) tga_web/templates/ — UI templates
# •	Not a Python package. No __init__.py.
# Role: Jinja templates: index.html, result.html.
# •	Important: because you use a blueprint named "web", templates must reference endpoints as:
# •	url_for('web.index')
# •	url_for('web.run_analysis')
# •	url_for('web.download', run_id=..., filename=...)
# •	And if you comment-out Jinja code, use Jinja comments {# ... #} not HTML comments.
# ________________________________________
# 8) tga_web/static/ — Static assets (optional)
# •	CSS/JS/images only. Not reports.
# •	________________________________________
# •	Runtime request flow
# •	Request: user opens UI
# •	GET /
# •	web.index route renders index.html
# •	Request: user runs analysis
# •	POST /run
# •	web.run_analysis receives form fields
# •	Calls AnalysisService.run(...)
# •	AnalysisService:
# •	normalizes URLs
# •	executes EXE
# •	asks RunRepository for newest run directory
# •	picks outputs
# •	returns AnalysisResult
# •	Route renders result.html with links
# •	Request: user downloads file
# •	GET /download/<run_id>/<filename>
# •	Route checks run_id exists and filename is inside run_dir
# •	send_file(...)
# ________________________________________



# •  Overall pattern: Single-file, procedural “pipeline” application (extract → fetch → prompt → LLM → render → publish/notify) with most concerns co-located.
# •  Strengths (structure):
# Clear end-to-end flow anchored in main().
# Stable output contract: Markdown as the canonical report, with HTML/DOCX/PPTX derived.
# Useful shared utilities already exist (URL validation, truncation, report naming, normalization).
# •  Primary structural issues:
# Mixed concerns: config loading, extraction, scraping, LLM calls, rendering, email, and UI logic live together.
# Global state: module-level config variables create hidden dependencies and hinder testing/reuse.
# Duplication/drift risk: multiple competing PPTX implementations and repeated imports; high maintenance overhead.
# Tight coupling: orchestration code is tightly bound to specific implementations (renderers, email wiring, paths).
# Hard process-exit behavior: fatal() deep in helpers exits the program, limiting reuse for web UI (prefer exceptions at boundaries).
# •  Design intent (what it wants to be):
# Thin entry points: CLI and Web UI should only gather inputs and call the app service.
# Single orchestrator: one GapAnalysisApp that coordinates the pipeline and returns a run result.
# Cohesive modules/services: separate adapters for document extraction, website fetching, LLM client, and renderers.
# Explicit data flow: Inputs → ExtractedText → Prompt → ReportMarkdown → Artifacts → Delivery.
# •  Recommended module split (high cohesion, low coupling):
# config.py (INI/env load; typed AppConfig)
# errors.py (validation + exception types)
# app.py (orchestrator/use-case)
# extractors/ (document + website)
# llm/ (prompt builder + OpenAI wrapper)
# render/ (markdown normalize + html/docx/pptx renderers)
# notify/ (emailer)
# io_paths.py (reports/run dir, file selection, open-with-default-app)
# •  Most important refactor actions:
# Consolidate PPTX to one implementation (single pptx_renderer.py with markdown_to_pptx_table_style, create_table_slide, table-chunking helpers).
# Replace globals with dependency injection (services constructed with AppConfig).
# Return a structured “RunResult” (paths, status, timing) for both CLI and web UI.
# Move termination to boundaries: raise exceptions in services; CLI/web layer handles exit/render diagnostics.
# •  Outcome if applied:
# Easier to modify PPTX/DOCX/HTML independently.
# Safer changes (less duplication and fewer side effects).
# Testable components (mock fetcher/LLM/extractor).
# Web UI and CLI share the same core engine cleanly.
