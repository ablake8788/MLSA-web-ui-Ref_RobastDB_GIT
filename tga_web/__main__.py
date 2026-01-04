from tga_web.app_factory import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=app.config["DEBUG"])

#############################
#
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
