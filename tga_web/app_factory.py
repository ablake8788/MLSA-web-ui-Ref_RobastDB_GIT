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









# # from flask import Flask
#
# from tga_web.config.ini_config import IniConfig
# from tga_web.repositories.run_repository import RunRepository
# from tga_web.services.analysis_service import AnalysisService
# from tga_web.services.url_normalization import GuessComUrlNormalizer
# from tga_web.web.routes import create_blueprint
#
# from tga_web.adapters.sqlserver_presets import SqlServerPresetRepository  # NEW
#
# from flask import Flask
#
# from tga_web.config.ini_config import IniConfig
# from tga_web.repositories.run_repository import RunRepository
# from tga_web.services.analysis_service import AnalysisService
# from tga_web.services.url_normalization import GuessComUrlNormalizer
# from tga_web.web.routes import create_blueprint
#
# from tga_web.adapters.sqlserver_presets import SqlServerPresetRepository  # NEW
#
#
# def create_app() -> Flask:
#     ini = IniConfig.from_env_or_default()
#     settings = ini.load_settings()
#
#     url_norm = GuessComUrlNormalizer(
#         default_scheme=settings.default_scheme,
#         guess_com_if_no_dot=settings.guess_com_if_no_dot,
#         no_guess_hosts=settings.no_guess_hosts,
#     )
#
#     run_repo = RunRepository(
#         reports_base=settings.reports_base,
#         exe_dir=settings.exe_path.parent,
#     )
#
#     analysis_service = AnalysisService(
#         exe_path=settings.exe_path,
#         timeout_seconds=settings.timeout_seconds,
#         url_normalizer=url_norm,
#         run_repo=run_repo,
#     )
#
#     # NEW: presets repo for dropdown
#     preset_repo = SqlServerPresetRepository(
#         ini_path=str(getattr(ini, "_ini_path", "MLSA_GapAnalysisRefDB.ini")),
#         table_name="dbo.GapAnalysisPresets",
#     )
#
#     app = Flask(__name__)
#
#     # CRITICAL FIX: pass preset_repo
#     app.register_blueprint(create_blueprint(analysis_service, preset_repo))
#
#     app.config["HOST"] = settings.flask_host
#     app.config["PORT"] = settings.flask_port
#     app.config["DEBUG"] = settings.flask_debug
#
#     return app
#
#
#
