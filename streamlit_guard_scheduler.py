"""streamlit_guard_scheduler.py

Aplicație Streamlit pentru a gestiona programul de gărzi (on‑call) într‑o foaie
Google și a oferi vizualizări Grid & Gantt. Include editor interactiv pentru
medici și suport pentru zile de indisponibilitate.

2025-06-15 v4.0 (Final & Robust)
────────────────
• FIX DEFINITIV: Implementată o funcție de încărcare `load_df` complet refăcută,
  care inspectează datele înainte de a le converti. Previne eroarea `TypeError`
  cauzată de coloane numerice complet goale în Google Sheets.
• ROBUSTEȚE: Validare strictă a datelor la încărcare pentru a elimina rândurile
  invalide și a standardiza tipurile de date.
• Toate celelalte îmbunătățiri de UI și logică din versiunile anterioare sunt păstrate.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Set, Tuple

import altair as alt
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
import gspread
from gspread.utils import rowcol_to_a1

# ──────────────────────────────────────────────────────────
# CONSTANTE
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
# Formatare opțională Google Sheets
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
# Wrappers pentru Google Sheets
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Conectare la Google API...")
def get_gsheet_client() -> gspread.Client:
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )
    return gspread.authorize(creds)

def _apply_format(ws: gspread.Worksheet, headers: List[str], rows: int = 1000) -> None:
    if not _FMT_AVAILABLE: return
    set_frozen(ws, rows=1)
    first_col, last_col = rowcol_to_a1(1, 1)[0], rowcol_to_a1(1, len(headers))[0]
    rng = f"{first_col}2:{last_col}{rows}"
    conditional_format(
        ws, rng,
        BooleanRule(
            condition={"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=ISEVEN(ROW())"}]},
            format=CellFormat(backgroundColor=Color(0.95, 0.95, 0.95)),
        ),
    )

def ensure_ws(sh: gspread.Spreadsheet, title: str, headers: List[str]) -> gspread.Worksheet:
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows="1000", cols=str(len(headers) + 2))
    if not any(ws.row_values(1)):
        ws.update([headers], value_input_option='USER_ENTERED')
    _apply_format(ws, headers)
    return ws

@st.cache_data(ttl=300, show_spinner="Încărcare și validare date...")
def load_and_clean_df(sheet_name: str) -> pd.DataFrame:
    """Încarcă datele, le validează și le curăță pentru a fi compatibile cu Streamlit."""
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    headers_map = {
        SHEET_DOCTORS: [COL_ID, COL_NAME, COL_SPEC, COL_MAX],
        SHEET_SCHEDULE: [COL_DATE, COL_SHIFT, COL_DOC_ID],
        SHEET_UNAVAIL: [COL_UNAV_DOC, COL_UNAV_DATE],
    }
    ws = ensure_ws(sh, sheet_name, headers_map[sheet_name])
    df = pd.DataFrame(ws.get_all_records()).reset_index(drop=True)

    # Proces de curățare specific pentru fiecare foaie
    if sheet_name == SHEET_DOCTORS:
        # 1. Asigură existența coloanelor esențiale
        for col in headers_map[SHEET_DOCTORS]:
            if col not in df.columns:
                df[col] = pd.NA
        
        # 2. Elimină rândurile fără un ID valid
        df[COL_ID] = df[COL_ID].replace("", pd.NA)
        df.dropna(subset=[COL_ID], inplace=True)
        
        # 3. Conversii sigure de tipuri
        df[COL_ID] = pd.to_numeric(df[COL_ID], errors="coerce").astype("Int64")
        df[COL_NAME] = df[COL_NAME].astype(str).fillna("")
        df[COL_SPEC] = df[COL_SPEC].astype(str).fillna("")
        
        # 4. Conversie condiționată pentru coloana numerică opțională
        if pd.to_numeric(df[COL_MAX], errors='coerce').notna().any():
            df[COL_MAX] = pd.to_numeric(df[COL_MAX], errors='coerce').astype('Int64')
        else:
             df[COL_MAX] = pd.NA # Dacă e goală, o umplem cu NA pentru a fi consistent
             df[COL_MAX] = df[COL_MAX].astype('Int64')


    elif sheet_name in [SHEET_SCHEDULE, SHEET_UNAVAIL]:
         # Curățare similară pentru celelalte foi dacă e necesar
        id_col = COL_DOC_ID if sheet_name == SHEET_SCHEDULE else COL_UNAV_DOC
        if id_col in df.columns:
            df.dropna(subset=[id_col], inplace=True)
            df[id_col] = pd.to_numeric(df[id_col], errors="coerce").astype("Int64")
    
    return df


def write_df(sheet_name: str, df: pd.DataFrame) -> None:
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    headers = list(df.columns)
    ws = ensure_ws(sh, sheet_name, headers)
    ws.clear()
    ws.update([headers] + df.fillna("").astype(str).values.tolist(), value_input_option='USER_ENTERED')
    _apply_format(ws, headers, rows=len(df) + 10)
    st.cache_data.clear()

# ... Restul codului (generate_schedule, show_schedule) rămâne identic ...
def generate_schedule(
    doctors_df: pd.DataFrame, unav_df: pd.DataFrame, start: dt.date, end: dt.date, shifts_per_day: int
) -> pd.DataFrame:
    valid_doctors = doctors_df.dropna(subset=[COL_ID])
    if valid_doctors.empty:
        raise ValueError("Nu există medici cu ID valid în tab-ul Doctors.")

    limits = {r[COL_ID]: int(r[COL_MAX]) if pd.notna(r[COL_MAX]) else 9999 for _, r in valid_doctors.iterrows()}
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
                    st.warning(f"Atenție {cur.strftime('%d-%m-%Y')}: Toți medicii sunt blocați. Se alocă forțat.", icon="⚠️")
                    warned_dates.add(cur)
                assigned = doc_ids[idx % len(doc_ids)]
                idx += 1
            
            rows.append({COL_DATE: cur.isoformat(), COL_SHIFT: f"Tură {s+1}", COL_DOC_ID: assigned})
        cur += dt.timedelta(days=1)
        
    return pd.DataFrame(rows)

def show_schedule(schedule_df: pd.DataFrame, doctors_df: pd.DataFrame) -> None:
    if schedule_df.empty:
        st.info("Momentan nu există un orar salvat. Poți genera unul nou din meniul din stânga.", icon="ℹ️")
        return

    id2name = doctors_df.set_index(COL_ID)[COL_NAME].to_dict()
    df = schedule_df.copy()
    # Asigură-te că maparea nu produce NaN dacă un ID nu e găsit
    df["doctor_name"] = df[COL_DOC_ID].map(id2name).fillna(f"ID {df[COL_DOC_ID]} negăsit")
    df["date_dt"] = pd.to_datetime(df[COL_DATE])

    view = st.radio("Alege vizualizare:", ["Grid", "Gantt"], horizontal=True, label_visibility="collapsed")
    
    if view == "Grid":
        st.dataframe(df.pivot(index=COL_DATE, columns=COL_SHIFT, values="doctor_name"), use_container_width=True)
    else:
        df["date_end"] = df["date_dt"] + pd.Timedelta(days=1)
        gantt = (
            alt.Chart(df).mark_bar(cornerRadius=5, height=20).encode(
                y=alt.Y("doctor_name:N", title="Medic", sort=None),
                x=alt.X("date_dt:T", title="Data"),
                x2=alt.X2("date_end:T"),
                color=alt.Color(COL_SHIFT, type="nominal", legend=alt.Legend(title="Tip Tură")),
                tooltip=[
                    alt.Tooltip("date_dt:T", title="Dată", format="%d %B %Y"),
                    alt.Tooltip("doctor_name:N", title="Medic"),
                    alt.Tooltip(COL_SHIFT, title="Tura"),
                ],
            ).properties(height=alt.Step(30))
        )
        st.altair_chart(gantt, use_container_width=True)


def main() -> None:
    """Funcția principală care rulează interfața Streamlit."""
    st.set_page_config(page_title="Orar Gărzi", layout="wide", initial_sidebar_state="expanded")
    st.title("🩺 Organizator de Gărzi v4.0")

    try:
        doctors_df_orig = load_and_clean_df(SHEET_DOCTORS)
        unav_df_orig = load_and_clean_df(SHEET_UNAVAIL)
        schedule_df = load_and_clean_df(SHEET_SCHEDULE)
    except Exception as e:
        st.error(f"A apărut o eroare la încărcarea și validarea datelor: {e}", icon="🔥")
        st.info("Verifică dacă foile de calcul din Google Sheets sunt formatate corect și încearcă din nou.")
        return

    with st.sidebar:
        st.header("🗓️ Perioadă Orar")
        today = dt.date.today()
        start_date = st.date_input("Început", today)
        end_date = st.date_input("Sfârșit", today + dt.timedelta(days=30))
        shifts_pd = st.number_input("Ture pe zi", 1, 4, 1)

        st.markdown("---")
        st.header("⚡ Acțiuni")
        if st.button("Generează Orar Nou", type="primary", use_container_width=True):
            with st.spinner("🧠 Se gândește algoritmul..."):
                try:
                    new_df = generate_schedule(doctors_df_orig, unav_df_orig, start_date, end_date, shifts_pd)
                    write_df(SHEET_SCHEDULE, new_df)
                    st.success("✅ Orar nou generat și salvat!", icon="🎉")
                    st.rerun()
                except (ValueError, IndexError) as e:
                    st.error(f"❌ {e}", icon="❗")

    tab1, tab2, tab3 = st.tabs(["🗓️ **Orar Gărzi**", "👩‍⚕️ **Lista Medici**", "🚫 **Indisponibilități**"])

    with tab1:
        st.header("Vizualizare Orar Curent")
        show_schedule(schedule_df, doctors_df_orig)

    with tab2:
        st.header("Editor Listă Medici")
        edited_doctors = st.data_editor(
            doctors_df_orig, num_rows_to_add=2, use_container_width=True, key="doc_editor"
        )
        if not edited_doctors.compare(doctors_df_orig).empty:
            write_df(SHEET_DOCTORS, edited_doctors)
            st.success("✅ Lista medicilor a fost salvată!")
            st.rerun()

    with tab3:
        st.header("Editor Indisponibilități")
        edited_unav = st.data_editor(
            unav_df_orig,
            num_rows_to_add=5,
            use_container_width=True,
            column_config={
                COL_UNAV_DOC: st.column_config.SelectboxColumn("ID Medic", options=doctors_df_orig[COL_ID].dropna().unique(), required=True),
                COL_UNAV_DATE: st.column_config.DateColumn("Data Indisponibilității", format="YYYY-MM-DD", required=True)
            },
            key="unav_editor"
        )
        if not edited_unav.compare(unav_df_orig).empty:
            write_df(SHEET_UNAVAIL, edited_unav)
            st.success("✅ Lista de indisponibilități a fost salvată!")
            st.rerun()

if __name__ == "__main__":
    main()
