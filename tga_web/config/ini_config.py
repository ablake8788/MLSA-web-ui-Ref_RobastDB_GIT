########## ini_config.py

import os
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

INI_DEFAULT_NAME = "MLSA_GapAnalysisRefDB.ini"


@dataclass(frozen=True)
class AppSettings:
    exe_path: Path
    reports_base: Path
    timeout_seconds: int

    default_scheme: str
    guess_com_if_no_dot: bool
    no_guess_hosts: set[str]

    flask_host: str
    flask_port: int
    flask_debug: bool

    # NEW: default instructions loaded from INI (used to prefill UI + fallback for runs)
    extra_instructions: str


class IniConfig:
    """
    Adapter around ConfigParser and filesystem resolution.
    Keeps INI handling out of your app/service code.
    """

    def __init__(self, ini_path: Path):
        self._ini_path = ini_path
        self._cfg = ConfigParser()
        read_ok = self._cfg.read(str(ini_path), encoding="utf-8-sig")
        if not read_ok:
            raise FileNotFoundError(f"INI file not found or unreadable: {ini_path}")

    @staticmethod
    def from_env_or_default() -> "IniConfig":
        ini_raw = (os.getenv("APP_INI") or "").strip()
        # If APP_INI is not set, default to repo-root-relative ini location
        ini_path = Path(ini_raw) if ini_raw else (Path(__file__).resolve().parents[2] / INI_DEFAULT_NAME)
        return IniConfig(ini_path)

    def _cfg_path(self, section: str, key: str) -> Path:
        """
        Reads a filesystem path from INI and resolves it.
        Tries [paths] and [path] interchangeably for convenience.
        """
        sections_to_try = [section]
        if section == "paths":
            sections_to_try.append("path")
        if section == "path":
            sections_to_try.append("paths")

        for sec in sections_to_try:
            if not self._cfg.has_section(sec):
                continue
            raw = (self._cfg.get(sec, key, fallback="") or "").strip()
            if raw:
                raw = os.path.expandvars(os.path.expanduser(raw))
                return Path(raw).resolve()

        raise FileNotFoundError(f"Missing INI value for {key} in sections: {sections_to_try}")

    def load_settings(self) -> AppSettings:
        # Required paths
        exe_path = self._cfg_path("paths", "exe_path")
        reports_base = self._cfg_path("paths", "reports_base")

        # Execution
        timeout_seconds = self._cfg.getint("execution", "timeout_seconds", fallback=1800)

        # URL normalization
        default_scheme = (self._cfg.get("url_normalization", "default_scheme", fallback="https") or "").strip() or "https"
        guess_com_if_no_dot = self._cfg.getboolean("url_normalization", "guess_com_if_no_dot", fallback=True)
        no_guess_hosts = {
            h.strip().lower()
            for h in (self._cfg.get("url_normalization", "no_guess_hosts", fallback="localhost") or "").split(",")
            if h.strip()
        }

        # NEW: prompt defaults (safe even if [prompt] section does not exist)
        extra_instructions = (self._cfg.get("prompt", "extra_instructions", fallback="") or "").strip()

        # Flask
        flask_host = (self._cfg.get("flask", "host", fallback="127.0.0.1") or "").strip() or "127.0.0.1"
        flask_port = self._cfg.getint("flask", "port", fallback=5000)
        flask_debug = self._cfg.getboolean("flask", "debug", fallback=True)

        # Validate
        if not exe_path.exists():
            raise FileNotFoundError(f"EXE not found: {exe_path}")

        reports_base.mkdir(parents=True, exist_ok=True)

        return AppSettings(
            exe_path=exe_path,
            reports_base=reports_base,
            timeout_seconds=timeout_seconds,
            default_scheme=default_scheme,
            guess_com_if_no_dot=guess_com_if_no_dot,
            no_guess_hosts=no_guess_hosts,
            flask_host=flask_host,
            flask_port=flask_port,
            flask_debug=flask_debug,
            extra_instructions=extra_instructions,
        )





# import os
# from configparser import ConfigParser
# from dataclasses import dataclass
# from pathlib import Path
#
# INI_DEFAULT_NAME = "TisGapAnalysisWebRef.ini"
#
#
# @dataclass(frozen=True)
# class AppSettings:
#     exe_path: Path
#     reports_base: Path
#     timeout_seconds: int
#
#     default_scheme: str
#     guess_com_if_no_dot: bool
#     no_guess_hosts: set[str]
#
#     flask_host: str
#     flask_port: int
#     flask_debug: bool
#
#     # NEW: default instructions loaded from INI (used to prefill UI + fallback for runs)
#     extra_instructions: str
#
#
# class IniConfig:
#     """
#     Adapter around ConfigParser and filesystem resolution.
#     Keeps INI handling out of your app/service code.
#     """
#
#     def __init__(self, ini_path: Path):
#         self._ini_path = ini_path
#         self._cfg = ConfigParser()
#         read_ok = self._cfg.read(str(ini_path), encoding="utf-8-sig")
#         if not read_ok:
#             raise FileNotFoundError(f"INI file not found or unreadable: {ini_path}")
#
#     @staticmethod
#     def from_env_or_default() -> "IniConfig":
#         ini_raw = (os.getenv("APP_INI") or "").strip()
#         # If APP_INI is not set, default to repo-root-relative ini location
#         ini_path = Path(ini_raw) if ini_raw else (Path(__file__).resolve().parents[2] / INI_DEFAULT_NAME)
#         return IniConfig(ini_path)
#
#     def _cfg_path(self, section: str, key: str) -> Path:
#         """
#         Reads a filesystem path from INI and resolves it.
#         Tries [paths] and [path] interchangeably for convenience.
#         """
#         sections_to_try = [section]
#         if section == "paths":
#             sections_to_try.append("path")
#         if section == "path":
#             sections_to_try.append("paths")
#
#         for sec in sections_to_try:
#             if not self._cfg.has_section(sec):
#                 continue
#             raw = (self._cfg.get(sec, key, fallback="") or "").strip()
#             if raw:
#                 raw = os.path.expandvars(os.path.expanduser(raw))
#                 return Path(raw).resolve()
#
#         raise FileNotFoundError(f"Missing INI value for {key} in sections: {sections_to_try}")
#
#     def load_settings(self) -> AppSettings:
#         # Required paths
#         exe_path = self._cfg_path("paths", "exe_path")
#         reports_base = self._cfg_path("paths", "reports_base")
#
#         # Execution
#         timeout_seconds = self._cfg.getint("execution", "timeout_seconds", fallback=1800)
#
#         # URL normalization
#         default_scheme = (self._cfg.get("url_normalization", "default_scheme", fallback="https") or "").strip() or "https"
#         guess_com_if_no_dot = self._cfg.getboolean("url_normalization", "guess_com_if_no_dot", fallback=True)
#         no_guess_hosts = {
#             h.strip().lower()
#             for h in (self._cfg.get("url_normalization", "no_guess_hosts", fallback="localhost") or "").split(",")
#             if h.strip()
#         }
#
#         # NEW: prompt defaults (safe even if [prompt] section does not exist)
#         extra_instructions = (self._cfg.get("prompt", "extra_instructions", fallback="") or "").strip()
#
#         # Flask
#         flask_host = (self._cfg.get("flask", "host", fallback="127.0.0.1") or "").strip() or "127.0.0.1"
#         flask_port = self._cfg.getint("flask", "port", fallback=5000)
#         flask_debug = self._cfg.getboolean("flask", "debug", fallback=True)
#
#         # Validate
#         if not exe_path.exists():
#             raise FileNotFoundError(f"EXE not found: {exe_path}")
#
#         reports_base.mkdir(parents=True, exist_ok=True)
#
#         return AppSettings(
#             exe_path=exe_path,
#             reports_base=reports_base,
#             timeout_seconds=timeout_seconds,
#             default_scheme=default_scheme,
#             guess_com_if_no_dot=guess_com_if_no_dot,
#             no_guess_hosts=no_guess_hosts,
#             flask_host=flask_host,
#             flask_port=flask_port,
#             flask_debug=flask_debug,
#             extra_instructions=extra_instructions,
#         )
#
#
#
#
# # import os
# # from configparser import ConfigParser
# # from dataclasses import dataclass
# # from pathlib import Path
# #
# # INI_DEFAULT_NAME = "TisGapAnalysisWebRef.ini"
# #
# #
# #
# # @dataclass(frozen=True)
# # class AppSettings:
# #     exe_path: Path
# #     reports_base: Path
# #     timeout_seconds: int
# #
# #     default_scheme: str
# #     guess_com_if_no_dot: bool
# #     no_guess_hosts: set[str]
# #
# #     flask_host: str
# #     flask_port: int
# #     flask_debug: bool
# #
# #
# # class IniConfig:
# #     """
# #     Adapter around ConfigParser and filesystem resolution.
# #     Keeps INI handling out of your app/service code.
# #     """
# #
# #     def __init__(self, ini_path: Path):
# #         self._ini_path = ini_path
# #         self._cfg = ConfigParser()
# #         read_ok = self._cfg.read(str(ini_path), encoding="utf-8-sig")
# #         if not read_ok:
# #             raise FileNotFoundError(f"INI file not found or unreadable: {ini_path}")
# #
# #     @staticmethod
# #     def from_env_or_default() -> "IniConfig":
# #         ini_raw = (os.getenv("APP_INI") or "").strip()
# #         ##ini_path = Path(ini_raw) if ini_raw else (Path(__file__).resolve().parents[1] / INI_DEFAULT_NAME)
# #         ini_path = Path(ini_raw) if ini_raw else (Path(__file__).resolve().parents[2] / INI_DEFAULT_NAME)
# #         return IniConfig(ini_path)
# #
# #     def _cfg_path(self, section: str, key: str) -> Path:
# #         sections_to_try = [section]
# #         if section == "paths":
# #             sections_to_try.append("path")
# #         if section == "path":
# #             sections_to_try.append("paths")
# #
# #         for sec in sections_to_try:
# #             if not self._cfg.has_section(sec):
# #                 continue
# #             raw = (self._cfg.get(sec, key, fallback="") or "").strip()
# #             if raw:
# #                 raw = os.path.expandvars(os.path.expanduser(raw))
# #                 return Path(raw).resolve()
# #
# #         raise FileNotFoundError(f"Missing INI value for {key} in sections: {sections_to_try}")
# #
# #     def load_settings(self) -> AppSettings:
# #         exe_path = self._cfg_path("paths", "exe_path")
# #         reports_base = self._cfg_path("paths", "reports_base")
# #
# #         timeout_seconds = self._cfg.getint("execution", "timeout_seconds", fallback=1800)
# #
# #         default_scheme = (self._cfg.get("url_normalization", "default_scheme", fallback="https") or "").strip() or "https"
# #         guess_com_if_no_dot = self._cfg.getboolean("url_normalization", "guess_com_if_no_dot", fallback=True)
# #         no_guess_hosts = {
# #             h.strip().lower()
# #             for h in (self._cfg.get("url_normalization", "no_guess_hosts", fallback="localhost") or "").split(",")
# #             if h.strip()
# #         }
# #
# #
# #         flask_host = (self._cfg.get("flask", "host", fallback="127.0.0.1") or "").strip() or "127.0.0.1"
# #         flask_port = self._cfg.getint("flask", "port", fallback=5000)
# #         flask_debug = self._cfg.getboolean("flask", "debug", fallback=True)
# #
# #
# #
# #         if not exe_path.exists():
# #             raise FileNotFoundError(f"EXE not found: {exe_path}")
# #
# #         reports_base.mkdir(parents=True, exist_ok=True)
# #
# #         return AppSettings(
# #             exe_path=exe_path,
# #             reports_base=reports_base,
# #             timeout_seconds=timeout_seconds,
# #             default_scheme=default_scheme,
# #             guess_com_if_no_dot=guess_com_if_no_dot,
# #             no_guess_hosts=no_guess_hosts,
# #             flask_host=flask_host,
# #             flask_port=flask_port,
# #             flask_debug=flask_debug,
# #         )
