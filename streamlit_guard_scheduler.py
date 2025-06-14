"""streamlit_guard_scheduler.py

Aplicație Streamlit pentru a gestiona programul de gărzi (on‑call) într‑o foaie
Google și a oferi vizualizări Grid & Gantt. Include editor interactiv pentru
medici și suport pentru zile de indisponibilitate.

2025-06-15 v7.0 (Production Ready)
────────────────
• CRITICAL FIX: Eliminată eroarea `NameError` care apărea în tab-ul de
  indisponibilități atunci când foaia `Doctors` era goală.
• DATA INTEGRITY:
  - Implementată o funcție sigură de conversie la string în `write_df` pentru a
    preveni scrierea de numere float (ex: "1.0") în Google Sheets.
  - Adăugată validare pentru unicitatea ID-urilor la salvarea medicilor.
• UI/UX FIXES & IMPROVEMENTS:
  - Domeniul de culori din graficul Gantt este acum dinamic, bazat pe turele
    reale din orar, prevenind afișarea culorilor greșite.
  - Filtrul de medici din tab-ul de orar este acum gol by default pentru a
    îmbunătăți performanța la încărcare cu un număr mare de medici.
  - Folosit `.equals()` pentru a preveni salvările redundante la modificări
    de tip de date în editor.
• ROBUSTNESS: Adăugată validare pentru intervalul de date (start_date <= end_date).
• OPTIMIZATION: Invalidarea cache-ului este specifică funcției de încărcare.
• CODE QUALITY: Ordine importuri conform isort, type hints complete,
  naming consistent, aserțiuni în funcțiile helper.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Set, Tuple

# Third-party imports
import altair as alt
import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

# ──────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────
SHEET_DOCTORS = "Doctors"
SHEET_SCHEDULE = "Schedule"
SHEET_UNAVAIL = "Unavailability"

COL_ID = "id"
COL_NAME = "name"
COL_SPEC = "speciality"
COL_MAX = "max_shifts_per_month"

COL_DATE = "date"
COL_SHIFT = "shift_name"
COL_DOC_ID = "doctor_id"

COL_UNAV_DOC = "doctor_id"
COL_UNAV_DATE = "date"

# ---------------------------------------------------------------------------
# Optional Google‑Sheets formatting (graceful fallback)
# ---------------------------------------------------------------------------
try:
    from gspread_formatting import (
        BooleanRule,
        CellFormat,
        Color,
        conditional_format,
        set_frozen,
    )
    _FMT_AVAILABLE = True
except ImportError:
    _FMT_AVAILABLE = False
    def set_frozen(ws, rows=1, cols=0) -> None: pass
    def conditional_format(*args, **kwargs) -> None: pass
    class Color:
        def __init__(self, r: float = 1, g: float = 1, b: float = 1) -> None: pass
    class BooleanRule:
        pass

# ---------------------------------------------------------------------------
# Google Sheets Wrappers
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Conectare la Google API...")
def get_gsheet_client() -> gspread.Client:
    """Returns an authorized gspread client using Streamlit secrets."""
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
        )
        return gspread.authorize(creds)
    except KeyError:
        st.error("Credentialele GCP (`gcp_service_account`) nu sunt configurate. Adauga-le in `secrets.toml`.")
        st.stop()
    except Exception as e:
        st.error(f"Eroare la autentificarea Google: {e}")
        st.stop()


def _get_col_letters(col_idx: int) -> str:
    """Helper function to get column letters (e.g., 28 -> 'AB')."""
    assert col_idx >= 1, "Column index must be 1-based."
    a1_notation = rowcol_to_a1(1, col_idx)
    match = re.match(r"([A-Z]+)", a1_notation)
    if match:
        return match.group(1)
    raise ValueError(f"Could not determine column letters for index {col_idx}")


def _apply_format(ws: gspread.Worksheet, headers: List[str], rows: int = 1000) -> None:
    """Applies standard formatting: frozen header and alternating row colors."""
    if not _FMT_AVAILABLE or not headers: return
    set_frozen(ws, rows=1)
    
    first_col_letter = _get_col_letters(1)
    last_col_letter = _get_col_letters(len(headers))
    
    rng = f"{first_col_letter}2:{last_col_letter}{rows}"
    conditional_format(
        ws, rng,
        BooleanRule(
            condition={"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=ISEVEN(ROW())"}]},
            format=CellFormat(backgroundColor=Color(0.95, 0.95, 0.95)),
        ),
    )


def ensure_ws(sh: gspread.Spreadsheet, title: str, headers: List[str]) -> gspread.Worksheet:
    """Ensures a worksheet exists and applies standard formatting."""
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows="1000", cols=str(len(headers) + 5))
    
    current_headers = ws.row_values(1)
    if not any(current_headers) or current_headers != headers:
        ws.update([headers], value_input_option='USER_ENTERED')

    _apply_format(ws, headers)
    return ws


@st.cache_data(ttl=300, show_spinner="Incarcare si validare date...")
def load_and_validate_df(sheet_name: str) -> pd.DataFrame:
    """Loads, validates, and cleans data from a specific sheet."""
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    headers_map = {
        SHEET_DOCTORS: [COL_ID, COL_NAME, COL_SPEC, COL_MAX],
        SHEET_SCHEDULE: [COL_DATE, COL_SHIFT, COL_DOC_ID],
        SHEET_UNAVAIL: [COL_UNAV_DOC, COL_UNAV_DATE],
    }
    ws = ensure_ws(sh, sheet_name, headers_map[sheet_name])
    df = pd.DataFrame(ws.get_all_records()).reset_index(drop=True)

    if sheet_name == SHEET_DOCTORS:
        for col in headers_map[SHEET_DOCTORS]:
            if col not in df.columns: df[col] = ''
        
        df[COL_ID] = df[COL_ID].replace("", pd.NA)
        df.dropna(subset=[COL_ID], inplace=True)
        
        df[COL_ID] = pd.to_numeric(df[COL_ID], errors="coerce").astype("Int64")
        df[COL_NAME] = df[COL_NAME].astype(str)
        df[COL_SPEC] = df[COL_SPEC].astype(str)
        
        if pd.to_numeric(df[COL_MAX], errors='coerce').notna().any():
            df[COL_MAX] = pd.to_numeric(df[COL_MAX], errors='coerce').astype('Int64')
        else:
            df[COL_MAX] = pd.Series(pd.NA, index=df.index, dtype='Int64')

    elif sheet_name in [SHEET_SCHEDULE, SHEET_UNAVAIL]:
        id_col = COL_DOC_ID if sheet_name == SHEET_SCHEDULE else COL_UNAV_DOC
        if id_col in df.columns:
            df.dropna(subset=[id_col], inplace=True)
            df[id_col] = pd.to_numeric(df[id_col], errors="coerce").astype("Int64")
    
    return df


def _to_clean_int_str(x: Any) -> str:
    """Safely converts a value to a clean integer string if possible."""
    if pd.isna(x): return ""
    s_val = str(x)
    # Checks for integers or floats that are whole numbers (e.g., '1', '1.0', '1.00')
    if re.fullmatch(r"\d+(\.0+)?", s_val):
        return str(int(float(s_val)))
    return s_val


def write_df(sheet_name: str, df: pd.DataFrame) -> None:
    """Writes a DataFrame to a sheet, with robust type conversion."""
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    headers = list(df.columns)
    ws = ensure_ws(sh, sheet_name, headers)
    
    df_str = df.copy()
    for col in df_str.columns:
        if pd.api.types.is_numeric_dtype(df_str[col]):
            df_str[col] = df_str[col].apply(_to_clean_int_str)
        else:
            df_str[col] = df_str[col].fillna("").astype(str)

    ws.clear()
    ws.update([headers] + df_str.values.tolist(), value_input_option='USER_ENTERED')
    _apply_format(ws, headers, rows=len(df) + 20)
    
    load_and_validate_df.clear()

# ---------------------------------------------------------------------------
# Scheduling Algorithm
# ---------------------------------------------------------------------------
def generate_schedule(
    doctors_df: pd.DataFrame, unav_df: pd.DataFrame, start: dt.date, end: dt.date, shifts_per_day: int
) -> pd.DataFrame:
    valid_doctors = doctors_df.dropna(subset=[COL_ID])
    if valid_doctors.empty:
        raise ValueError("Nu exista medici cu ID valid in tab-ul Doctors.")

    limits = {}
    for _, r in valid_doctors.iterrows():
        max_val = 9999
        if str(r[COL_MAX]).strip().isdigit():
            max_val = int(r[COL_MAX])
        limits[r[COL_ID]] = max_val

    doc_ids = list(limits.keys())

    unav_set = {
        (r[COL_UNAV_DOC], pd.to_datetime(r[COL_UNAV_DATE]).date().isoformat())
        for _, r in unav_df.dropna(subset=[COL_UNAV_DOC, COL_UNAV_DATE]).iterrows()
    }

    counts: Dict[int, Dict[Tuple[int, int], int]] = {d: {} for d in doc_ids}
    rows: List[Dict] = []
    idx = 0
    cur = start
    warned_dates: Set[dt.date] = set()

    while cur <= end:
        mkey = (cur.year, cur.month)
        for s in range(shifts_per_day):
            assigned = None
            for attempt in range(len(doc_ids)):
                doc_id = doc_ids[(idx + attempt) % len(doc_ids)]
                if (doc_id, cur.isoformat()) in unav_set: continue
                if counts.setdefault(doc_id, {}).get(mkey, 0) >= limits[doc_id]: continue
                
                assigned = doc_id
                counts[doc_id][mkey] = counts[doc_id].get(mkey, 0) + 1
                idx += attempt + 1
                break
            
            if assigned is None:
                if cur not in warned_dates:
                    st.warning(f"Atentie {cur.strftime('%d-%m-%Y')}: Toti medicii sunt blocati. Se aloca fortat.", icon="⚠️")
                    warned_dates.add(cur)
                assigned = doc_ids[idx % len(doc_ids)]
                idx += 1
            
            rows.append({COL_DATE: cur.isoformat(), COL_SHIFT: f"Tura {s+1}", COL_DOC_ID: assigned})
        cur += dt.timedelta(days=1)
        
    return pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------
def show_schedule(schedule_df: pd.DataFrame, doctors_df: pd.DataFrame) -> None:
    """Displays the schedule as a Grid or Gantt chart, with filtering."""
    if schedule_df.empty:
        st.info("Momentan nu exista un orar salvat. Poti genera unul nou din meniul din stanga.", icon="ℹ️")
        return

    if COL_ID not in doctors_df.columns:
        st.error("Coloana 'id' lipseste din foaia 'Doctors'. Verificati formatul fisierului.")
        return
        
    id2name = doctors_df.set_index(COL_ID)[COL_NAME].to_dict()
    df = schedule_df.copy()
    df["doctor_name"] = df[COL_DOC_ID].map(id2name).fillna("ID Necunoscut")
    
    all_doctors = sorted(df["doctor_name"].unique())
    selected_doctors = st.multiselect("Filtreaza dupa medic:", options=all_doctors, placeholder="Alege medic(i)...")
    
    if not selected_doctors:
        st.info("Selecteaza cel putin un medic pentru a afisa orarul.")
        return
    
    df = df[df["doctor_name"].isin(selected_doctors)]
    df["date_dt"] = pd.to_datetime(df[COL_DATE])

    view = st.radio("Alege vizualizare:", ["Grid", "Gantt"], horizontal=True, label_visibility="collapsed")
    
    if view == "Grid":
        df = df.sort_values(by="date_dt")
        st.dataframe(df.pivot(index=COL_DATE, columns=COL_SHIFT, values="doctor_name"), use_container_width=True)
    else:
        df["date_end"] = df["date_dt"] + pd.Timedelta(days=1)
        # MEDIUM FIX: Dynamic color domain based on actual data
        shift_domain = sorted(df[COL_SHIFT].unique())
        
        gantt_chart = (
            alt.Chart(df).mark_bar(cornerRadius=5, height=20).encode(
                y=alt.Y("doctor_name:N", title="Medic", sort=None),
                x=alt.X("date_dt:T", title="Data"),
                x2=alt.X2("date_end:T"),
                color=alt.Color(
                    COL_SHIFT, type="nominal", legend=alt.Legend(title="Tip Tura"),
                    scale=alt.Scale(domain=shift_domain)
                ),
                tooltip=[
                    alt.Tooltip("date_dt:T", title="Data", format="%d %B %Y"),
                    alt.Tooltip("doctor_name:N", title="Medic"),
                    alt.Tooltip(COL_SHIFT, title="Tura"),
                ],
            ).properties(height=alt.Step(30))
        )
        st.altair_chart(gantt_chart, use_container_width=True)


def main() -> None:
    """Main function to run the Streamlit UI."""
    st.set_page_config(page_title="Orar Garzi", layout="wide", initial_sidebar_state="expanded")
    st.title("🩺 Organizator de Garzi v7.0")

    try:
        doctors_df_orig = load_and_validate_df(SHEET_DOCTORS)
        unav_df_orig = load_and_validate_df(SHEET_UNAVAIL)
        schedule_df = load_and_validate_df(SHEET_SCHEDULE)
    except Exception as e:
        st.error(f"A aparut o eroare critica la incarcarea datelor: {e}", icon="🔥")
        return

    with st.sidebar:
        st.header("🗓️ Perioada Orar")
        today = dt.date.today()
        start_date = st.date_input("Inceput", today)
        end_date = st.date_input("Sfarsit", today + dt.timedelta(days=30))
        shifts_per_day = st.number_input("Ture pe zi", 1, 4, 1)

        if start_date > end_date:
            st.error("Data de inceput trebuie sa fie inainte de data de sfarsit.")
            st.stop()

        st.markdown("---")
        st.header("⚡ Actiuni")
        if st.button("Genereaza Orar Nou", type="primary", use_container_width=True):
            with st.spinner("🧠 Se gandeste algoritmul..."):
                try:
                    new_df = generate_schedule(doctors_df_orig, unav_df_orig, start_date, end_date, shifts_per_day)
                    write_df(SHEET_SCHEDULE, new_df)
                    st.success("✅ Orar nou generat si salvat!", icon="🎉")
                    st.rerun()
                except (ValueError, IndexError) as e:
                    st.error(f"❌ {e}", icon="❗")

    tab1, tab2, tab3 = st.tabs(["🗓️ **Orar Garzi**", "👩‍⚕️ **Lista Medici**", "🚫 **Indisponibilitati**"])

    with tab1:
        st.header("Vizualizare Orar Curent")
        show_schedule(schedule_df, doctors_df_orig)

    with tab2:
        st.header("Editor Lista Medici")
        edited_doctors = st.data_editor(
            doctors_df_orig,
            num_rows_to_add=2, use_container_width=True, key="doc_editor",
            column_config={
                 COL_ID: st.column_config.NumberColumn("ID (Unic)", required=True, step=1, min_value=1),
                 COL_NAME: "Nume Medic",
                 COL_SPEC: "Specialitate",
                 COL_MAX: st.column_config.NumberColumn("Garzi Max/Luna", min_value=0, step=1)
            }
        )
        if not edited_doctors.equals(doctors_df_orig):
            # MINOR FIX: Add uniqueness validation before writing
            if edited_doctors[COL_ID].duplicated().any():
                st.error("EROARE: Exista ID-uri duplicate. Fiecare medic trebuie sa aiba un ID unic.")
            else:
                write_df(SHEET_DOCTORS, edited_doctors)
                st.success("✅ Lista medicilor a fost salvata!")
                st.rerun()

    with tab3:
        st.header("Editor Indisponibilitati")
        # CRITICAL FIX: Initialize map before the if block to prevent NameError
        doc_id_map: Dict[int, str] = {}
        doc_id_options: List[int] = []
        if not doctors_df_orig.empty and COL_ID in doctors_df_orig.columns:
            doc_id_map = doctors_df_orig.set_index(COL_ID)[COL_NAME].to_dict()
            doc_id_options = sorted(doc_id_map.keys(), key=lambda x: doc_id_map[x])

        edited_unav = st.data_editor(
            unav_df_orig,
            num_rows_to_add=5, use_container_width=True,
            column_config={
                COL_UNAV_DOC: st.column_config.SelectboxColumn(
                    "Medic", options=doc_id_options, 
                    format_func=lambda x: f"{x} - {doc_id_map.get(x, 'Nume Necunoscut')}" if x else "",
                    required=True
                ),
                COL_UNAV_DATE: st.column_config.DateColumn("Data Indisponibilitatii", format="YYYY-MM-DD", required=True)
            },
            key="unav_editor"
        )
        if not edited_unav.equals(unav_df_orig):
            write_df(SHEET_UNAVAIL, edited_unav)
            st.success("✅ Lista de indisponibilitati a fost salvata!")
            st.rerun()

if __name__ == "__main__":
    main()
