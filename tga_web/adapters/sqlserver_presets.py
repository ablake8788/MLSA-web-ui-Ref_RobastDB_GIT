##
# sqlserver_presets.py
## for drop-downs
## pip install streamlit
# import streamlit as st


import os
import sys
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from functools import lru_cache

# -----------------------------
# Config
# -----------------------------
DEFAULT_CONN_STR = (
    "mssql+pyodbc:///?odbc_connect="
    "DRIVER%3D%7BODBC+Driver+17+for+SQL+Server%7D%3B"
    "SERVER%3Dlocalhost%3B"
    "DATABASE%3DPBI_Projects%3B"
    "Trusted_Connection%3Dyes%3B"
    "Encrypt%3Dno%3B"
    "TrustServerCertificate%3Dyes"
)

TABLE_NAME = "dbo.GapAnalysisPresets"


# -----------------------------
# DB helpers
# -----------------------------
def get_engine(conn_str: str) -> Engine:
    try:
        return create_engine(conn_str, pool_pre_ping=True, future=True)
    except Exception as e:
        raise RuntimeError(f"Failed to create DB engine: {e}") from e


def fetch_presets(engine: Engine, companyname: str) -> list[str]:
    """
    Returns a distinct list of preset_display_name for a given company.
    """
    q = text(f"""
        SELECT DISTINCT preset_display_name
        FROM {TABLE_NAME}
        WHERE companyname = :companyname
          AND preset_display_name IS NOT NULL
          AND LTRIM(RTRIM(preset_display_name)) <> ''
        ORDER BY preset_display_name;
    """)

    df = pd.read_sql(q, engine, params={"companyname": companyname})
    return df["preset_display_name"].astype(str).tolist()


def fetch_one_preset(engine: Engine, companyname: str, preset_display_name: str) -> list[str]:
    """
    Returns the preset only if it exists for that company.
    (This matches your exact SQL filter.)
    """
    q = text(f"""
        SELECT DISTINCT preset_display_name
        FROM {TABLE_NAME}
        WHERE 1=1 AND
        #preset_display_name = :preset_display_name
          AND companyname = :companyname
        ORDER BY preset_display_name;
    """)

    df = pd.read_sql(q, engine, params={
        "companyname": companyname,
        "preset_display_name": preset_display_name
    })
    return df["preset_display_name"].astype(str).tolist()


# -----------------------------
# Streamlit UI
# -----------------------------
def main() -> None:
    st.set_page_config(page_title="Preset Dropdown", layout="centered")
    st.title("Gap Analysis Preset Selector")

    # Connection string: env var wins
    conn_str = os.environ.get("DB_CONN_STR", "").strip() or DEFAULT_CONN_STR

    with st.expander("Connection", expanded=False):
        st.write("Using DB connection from `DB_CONN_STR` env var if set, else default local connection.")
        st.code(conn_str, language="text")

    # Inputs
    companyname = st.text_input("Company name", value="TIS")
    exact_filter = st.checkbox("Use exact filter (Compliance & Policy Gap only)", value=False)

    # Connect
    try:
        engine = get_engine(conn_str)
    except Exception as e:
        st.error(str(e))
        st.stop()

    # Load options
    try:
        if exact_filter:
            options = fetch_one_preset(engine, companyname=companyname, preset_display_name="Compliance & Policy Gap")
        else:
            options = fetch_presets(engine, companyname=companyname)
    except Exception as e:
        st.error(f"DB query failed: {e}")
        st.stop()

    if not options:
        st.warning("No presets found for the selected filters.")
        st.stop()

    # Preselect if present
    default_name = "Compliance & Policy Gap"
    default_index = options.index(default_name) if default_name in options else 0

    selected = st.selectbox(
        "Preset Display Name",
        options=options,
        index=default_index
    )

    st.success(f"Selected preset: {selected}")

    # Example: return the value for downstream use
    st.subheader("Value to pass into your pipeline")
    st.code(f'preset_display_name = "{selected}"', language="python")


if __name__ == "__main__":
    # Run: streamlit run preset_dropdown_app.py
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)











# from __future__ import annotations
#
# from dataclasses import dataclass
# from configparser import ConfigParser
# from typing import List, Optional
#
# import pyodbc
#
#
# @dataclass(frozen=True)
# class Preset:
#     preset_id: int
#     companyname: str
#
#     # This is what your existing dropdown likely displays today.
#     # We will populate THIS with the combined label.
#     preset_display_name: str
#
#     # Keep original DB value here so you don't lose it.
#     preset_display_name_raw: str
#
#     competitor: str
#     baseline: str
#     instruction_preset: str
#     extra_instructions: str
#     source_file_path: str
#     web: str
#     processor: str
#     is_active: bool
#
#     @property
#     def display_label(self) -> str:
#         c = (self.companyname or "").strip()
#         n = (self.preset_display_name_raw or "").strip()
#         if c and n:
#             return f"{c} - {n}"
#         return c or n or f"Preset {self.preset_id}"
#
#     def __str__(self) -> str:
#         return self.display_label
#
#
# class SqlServerPresetRepository:
#     def __init__(self, ini_path: str, table_name: str = "dbo.GapAnalysisPresets"):
#         self.ini_path = ini_path
#         self.table_name = table_name
#
#         cfg = ConfigParser()
#         ok = cfg.read(self.ini_path, encoding="utf-8-sig")
#         if not ok:
#             raise FileNotFoundError(f"INI not found or unreadable: {self.ini_path}")
#
#         if "sqlserver" not in cfg:
#             raise KeyError("Missing [sqlserver] section in INI")
#
#         s = cfg["sqlserver"]
#         self._driver = (s.get("driver", "ODBC Driver 17 for SQL Server") or "").strip()
#         self._server = (s.get("server", "localhost") or "").strip()
#         self._database = (s.get("database", "") or "").strip()
#         self._username = (s.get("username", "") or "").strip()
#         self._password = (s.get("password", "") or "").strip()
#
#         trust_raw = (s.get("trust_cert", "yes") or "").strip().lower()
#         self._trust_cert = trust_raw in ("yes", "true", "1")
#
#         if not self._database:
#             raise ValueError("sqlserver.database is empty in INI")
#
#     def _connect(self):
#         parts = [
#             f"DRIVER={{{self._driver}}}",
#             f"SERVER={self._server}",
#             f"DATABASE={self._database}",
#         ]
#
#         if self._username:
#             parts.append(f"UID={self._username}")
#             parts.append(f"PWD={self._password}")
#         else:
#             parts.append("Trusted_Connection=yes")
#
#         if self._trust_cert:
#             parts.append("TrustServerCertificate=yes")
#
#         conn_str = ";".join(parts) + ";"
#         return pyodbc.connect(conn_str)
#
#     @staticmethod
#     def _get(r, name: str, default=""):
#         return getattr(r, name, default)
#
#     @staticmethod
#     def _make_display_label(companyname: str, preset_display_name_raw: str, preset_id: int) -> str:
#         c = (companyname or "").strip()
#         n = (preset_display_name_raw or "").strip()
#         if c and n:
#             return f"{c} - {n}"
#         return c or n or f"Preset {preset_id}"
#
#     def get_active_presets(self) -> List[Preset]:
#         q = f"""
#         SELECT
#             preset_id,
#             companyname,
#             preset_display_name,
#             competitor,
#             baseline,
#             instruction_preset,
#             extra_instructions,
#             source_file_path,
#             web,
#             processor,
#             is_active
#         FROM {self.table_name}
#         WHERE is_active = 1
#         ORDER BY companyname, preset_display_name
#         """
#
#         with self._connect() as conn:
#             cur = conn.cursor()
#             rows = cur.execute(q).fetchall()
#
#         out: List[Preset] = []
#         for r in rows:
#             preset_id = int(self._get(r, "preset_id", 0))
#             companyname = str(self._get(r, "companyname", "") or "")
#             preset_display_name_raw = str(self._get(r, "preset_display_name", "") or "")
#
#             # IMPORTANT: set preset_display_name to the combined label
#             # so dropdowns that already display preset_display_name will show the combined string.
#             combined = self._make_display_label(companyname, preset_display_name_raw, preset_id)
#
#             out.append(
#                 Preset(
#                     preset_id=preset_id,
#                     companyname=companyname,
#                     preset_display_name=combined,            # <- dropdown shows this
#                     preset_display_name_raw=preset_display_name_raw,  # <- original DB value preserved
#                     competitor=str(self._get(r, "competitor", "") or ""),
#                     baseline=str(self._get(r, "baseline", "") or ""),
#                     instruction_preset=str(self._get(r, "instruction_preset", "") or ""),
#                     extra_instructions=str(self._get(r, "extra_instructions", "") or ""),
#                     source_file_path=str(self._get(r, "source_file_path", "") or ""),
#                     web=str(self._get(r, "web", "") or ""),
#                     processor=str(self._get(r, "processor", "") or ""),
#                     is_active=bool(self._get(r, "is_active", True)),
#                 )
#             )
#
#         return out
#
#     def get_preset(self, preset_id: int) -> Optional[Preset]:
#         q = f"""
#         SELECT
#             preset_id,
#             companyname,
#             preset_display_name,
#             competitor,
#             baseline,
#             instruction_preset,
#             extra_instructions,
#             source_file_path,
#             web,
#             processor,
#             is_active
#         FROM {self.table_name}
#         WHERE preset_id = ?
#           AND is_active = 1
#         """
#
#         with self._connect() as conn:
#             cur = conn.cursor()
#             r = cur.execute(q, preset_id).fetchone()
#
#         if not r:
#             return None
#
#         companyname = str(self._get(r, "companyname", "") or "")
#         preset_display_name_raw = str(self._get(r, "preset_display_name", "") or "")
#         combined = self._make_display_label(companyname, preset_display_name_raw, preset_id)
#
#         return Preset(
#             preset_id=int(self._get(r, "preset_id", 0)),
#             companyname=companyname,
#             preset_display_name=combined,                 # <- combined for UI
#             preset_display_name_raw=preset_display_name_raw,
#             competitor=str(self._get(r, "competitor", "") or ""),
#             baseline=str(self._get(r, "baseline", "") or ""),
#             instruction_preset=str(self._get(r, "instruction_preset", "") or ""),
#             extra_instructions=str(self._get(r, "extra_instructions", "") or ""),
#             source_file_path=str(self._get(r, "source_file_path", "") or ""),
#             web=str(self._get(r, "web", "") or ""),
#             processor=str(self._get(r, "processor", "") or ""),
#             is_active=bool(self._get(r, "is_active", True)),
#         )
#
#     def get_distinct_instruction_presets(self) -> list[str]:
#         sql = f"""
#         SELECT DISTINCT instruction_preset
#         FROM {self.table_name}
#         WHERE is_active = 1
#           AND instruction_preset IS NOT NULL
#           AND LTRIM(RTRIM(instruction_preset)) <> ''
#         ORDER BY instruction_preset
#         """
#         with self._connect() as conn:
#             cur = conn.cursor()
#             rows = cur.execute(sql).fetchall()
#             return [str(r[0]) for r in rows]
