from __future__ import annotations

from dataclasses import dataclass
from configparser import ConfigParser
from typing import List, Optional

import pyodbc


@dataclass(frozen=True)
class Preset:
    preset_id: int
    companyname: str

    # This is what your existing dropdown likely displays today.
    # We will populate THIS with the combined label.
    preset_display_name: str

    # Keep original DB value here so you don't lose it.
    preset_display_name_raw: str

    competitor: str
    baseline: str
    instruction_preset: str
    extra_instructions: str
    source_file_path: str
    web: str
    processor: str
    is_active: bool

    @property
    def display_label(self) -> str:
        c = (self.companyname or "").strip()
        n = (self.preset_display_name_raw or "").strip()
        if c and n:
            return f"{c} - {n}"
        return c or n or f"Preset {self.preset_id}"

    def __str__(self) -> str:
        return self.display_label


class SqlServerPresetRepository:
    def __init__(self, ini_path: str, table_name: str = "dbo.GapAnalysisPresets"):
        self.ini_path = ini_path
        self.table_name = table_name

        cfg = ConfigParser()
        ok = cfg.read(self.ini_path, encoding="utf-8-sig")
        if not ok:
            raise FileNotFoundError(f"INI not found or unreadable: {self.ini_path}")

        if "sqlserver" not in cfg:
            raise KeyError("Missing [sqlserver] section in INI")

        s = cfg["sqlserver"]
        self._driver = (s.get("driver", "ODBC Driver 17 for SQL Server") or "").strip()
        self._server = (s.get("server", "localhost") or "").strip()
        self._database = (s.get("database", "") or "").strip()
        self._username = (s.get("username", "") or "").strip()
        self._password = (s.get("password", "") or "").strip()

        trust_raw = (s.get("trust_cert", "yes") or "").strip().lower()
        self._trust_cert = trust_raw in ("yes", "true", "1")

        if not self._database:
            raise ValueError("sqlserver.database is empty in INI")

    def _connect(self):
        parts = [
            f"DRIVER={{{self._driver}}}",
            f"SERVER={self._server}",
            f"DATABASE={self._database}",
        ]

        if self._username:
            parts.append(f"UID={self._username}")
            parts.append(f"PWD={self._password}")
        else:
            parts.append("Trusted_Connection=yes")

        if self._trust_cert:
            parts.append("TrustServerCertificate=yes")

        conn_str = ";".join(parts) + ";"
        return pyodbc.connect(conn_str)

    @staticmethod
    def _get(r, name: str, default=""):
        return getattr(r, name, default)

    @staticmethod
    def _make_display_label(companyname: str, preset_display_name_raw: str, preset_id: int) -> str:
        c = (companyname or "").strip()
        n = (preset_display_name_raw or "").strip()
        if c and n:
            return f"{c} - {n}"
        return c or n or f"Preset {preset_id}"

    def get_active_presets(self) -> List[Preset]:
        q = f"""
        SELECT
            preset_id,
            companyname,
            preset_display_name,
            competitor,
            baseline,
            instruction_preset,
            extra_instructions,
            source_file_path,
            web,
            processor,
            is_active
        FROM {self.table_name}
        WHERE is_active = 1
        ORDER BY companyname, preset_display_name
        """

        with self._connect() as conn:
            cur = conn.cursor()
            rows = cur.execute(q).fetchall()

        out: List[Preset] = []
        for r in rows:
            preset_id = int(self._get(r, "preset_id", 0))
            companyname = str(self._get(r, "companyname", "") or "")
            preset_display_name_raw = str(self._get(r, "preset_display_name", "") or "")

            # IMPORTANT: set preset_display_name to the combined label
            # so dropdowns that already display preset_display_name will show the combined string.
            combined = self._make_display_label(companyname, preset_display_name_raw, preset_id)

            out.append(
                Preset(
                    preset_id=preset_id,
                    companyname=companyname,
                    preset_display_name=combined,            # <- dropdown shows this
                    preset_display_name_raw=preset_display_name_raw,  # <- original DB value preserved
                    competitor=str(self._get(r, "competitor", "") or ""),
                    baseline=str(self._get(r, "baseline", "") or ""),
                    instruction_preset=str(self._get(r, "instruction_preset", "") or ""),
                    extra_instructions=str(self._get(r, "extra_instructions", "") or ""),
                    source_file_path=str(self._get(r, "source_file_path", "") or ""),
                    web=str(self._get(r, "web", "") or ""),
                    processor=str(self._get(r, "processor", "") or ""),
                    is_active=bool(self._get(r, "is_active", True)),
                )
            )

        return out

    def get_preset(self, preset_id: int) -> Optional[Preset]:
        q = f"""
        SELECT
            preset_id,
            companyname,
            preset_display_name,
            competitor,
            baseline,
            instruction_preset,
            extra_instructions,
            source_file_path,
            web,
            processor,
            is_active
        FROM {self.table_name}
        WHERE preset_id = ?
          AND is_active = 1
        """

        with self._connect() as conn:
            cur = conn.cursor()
            r = cur.execute(q, preset_id).fetchone()

        if not r:
            return None

        companyname = str(self._get(r, "companyname", "") or "")
        preset_display_name_raw = str(self._get(r, "preset_display_name", "") or "")
        combined = self._make_display_label(companyname, preset_display_name_raw, preset_id)

        return Preset(
            preset_id=int(self._get(r, "preset_id", 0)),
            companyname=companyname,
            preset_display_name=combined,                 # <- combined for UI
            preset_display_name_raw=preset_display_name_raw,
            competitor=str(self._get(r, "competitor", "") or ""),
            baseline=str(self._get(r, "baseline", "") or ""),
            instruction_preset=str(self._get(r, "instruction_preset", "") or ""),
            extra_instructions=str(self._get(r, "extra_instructions", "") or ""),
            source_file_path=str(self._get(r, "source_file_path", "") or ""),
            web=str(self._get(r, "web", "") or ""),
            processor=str(self._get(r, "processor", "") or ""),
            is_active=bool(self._get(r, "is_active", True)),
        )

    def get_distinct_instruction_presets(self) -> list[str]:
        sql = f"""
        SELECT DISTINCT instruction_preset
        FROM {self.table_name}
        WHERE is_active = 1
          AND instruction_preset IS NOT NULL
          AND LTRIM(RTRIM(instruction_preset)) <> ''
        ORDER BY instruction_preset
        """
        with self._connect() as conn:
            cur = conn.cursor()
            rows = cur.execute(sql).fetchall()
            return [str(r[0]) for r in rows]
