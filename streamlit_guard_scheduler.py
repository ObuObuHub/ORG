"""streamlit_guard_scheduler.py
Streamlit app for managing hospital on-call (garda) rosters powered by Google Sheets.

CHANGELOG (2025‑06‑14)
----------------------
• Added ALT‑air heat‑map & pivot‑table visualisations so the schedule is visible in the app.
• Added automatic creation of the required Google‑Sheets worksheets with frozen header & basic colour‑banding for clarity.
• Added error guards when doctor list is empty.
• Added requirements comment (`altair`, `gspread-formatting`).

Prerequisites
-------------
1. Service‑account & `secrets.toml` as before (see previous instructions).
2. **Install extra packages**: add to `requirements.txt`:
   ````
   altair==5.3
   gspread-formatting==1.1.2
   ````

Google Sheets layout
--------------------
Still two tabs (`Doctors`, `Schedule`).  If the tab is missing, the app now
creates it with headers and applies conditional formatting (striped rows).

"""
from __future__ import annotations

import datetime as dt
from typing import List, Dict

import altair as alt  # NEW
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
import gspread
from gspread_formatting import (  # type: ignore
    CellFormat, Color, format_cell_range, set_frozen, TextFormat, conditional_format, BooleanRule, GradientRule
)

# ────────────────────────────────────────────────────────────────────────────────
# Google‑Sheets helpers
# ────────────────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_gsheet_client():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scope
    )
    return gspread.authorize(creds)


def ensure_worksheet(sh, title: str, headers: List[str], rows: int = 200, cols: int = 20):
    """Ensure worksheet exists & has headers; apply simple formatting."""
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=str(rows), cols=str(cols))
    # add headers if first row empty
    if not any(ws.row_values(1)):
        ws.update([headers])
    # freeze header
    set_frozen(ws, rows=1)
    # striped rows conditional formatting for readability
    first_col_letter = gspread.utils.rowcol_to_a1(1, 1)[0]
    last_col_letter = gspread.utils.rowcol_to_a1(1, len(headers))[0]
    range_a1 = f"{first_col_letter}2:{last_col_letter}{rows}"
    conditional_format(
        ws, range_a1,
        BooleanRule(
            condition={'type': 'CUSTOM_FORMULA', 'values': [{'userEnteredValue': '=ISEVEN(ROW())'}]},
            format=CellFormat(backgroundColor=Color(0.95, 0.95, 0.95))
        )
    )
    return ws


@st.cache_data(ttl=300)
def load_sheet(sheet_name: str) -> pd.DataFrame:
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    # auto‑create sheets with headers if missing
    if sheet_name == "Doctors":
        ws = ensure_worksheet(sh, "Doctors", ["id", "name", "speciality", "max_shifts_per_month"])
    else:
        ws = ensure_worksheet(sh, "Schedule", ["date", "shift_name", "doctor_id"])
    df = pd.DataFrame(ws.get_all_records())
    return df


def write_schedule(df: pd.DataFrame):
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    ws = ensure_worksheet(sh, "Schedule", ["date", "shift_name", "doctor_id"])
    ws.clear()
    ws.update([df.columns.values.tolist()] + df.values.tolist())
    set_frozen(ws, rows=1)

# ────────────────────────────────────────────────────────────────────────────────
# Simple round‑robin scheduler
# ────────────────────────────────────────────────────────────────────────────────

def generate_round_robin(doctors: List[int], start: dt.date, end: dt.date, shifts_per_day: int = 1) -> pd.DataFrame:
    if not doctors:
        raise ValueError("Lista medicilor este goală – adaugă cel puțin un medic.")
    days = (end - start).days + 1
    doctor_cycle = doctors * ((days * shifts_per_day) // len(doctors) + 1)
    rows: List[Dict] = []
    idx = 0
    for n in range(days):
        d = start + dt.timedelta(days=n)
        for s in range(shifts_per_day):
            rows.append({"date": d.isoformat(), "shift_name": f"Shift {s+1}", "doctor_id": doctor_cycle[idx]})
            idx += 1
    return pd.DataFrame(rows)

# ────────────────────────────────────────────────────────────────────────────────
# Streamlit UI
# ────────────────────────────────────────────────────────────────────────────────

def show_schedule_table(schedule_df: pd.DataFrame, doctors_df: pd.DataFrame):
    """Pivot schedule into calendar‑style table and render altair heatmap."""
    # Map id → name
    id2name = doctors_df.set_index("id")["name"].to_dict()
    schedule_df["doctor_name"] = schedule_df["doctor_id"].map(id2name)

    # Wide pivot table (date × shift)
    pivot = schedule_df.pivot(index="date", columns="shift_name", values="doctor_name")
    st.subheader("📅 Calendar (pivot table)")
    st.dataframe(pivot, use_container_width=True)

    # Altair heatmap
    st.subheader("🖼️ Vizualizare grafică")
    try:
        schedule_df["date"] = pd.to_datetime(schedule_df["date"])
        chart = (
            alt.Chart(schedule_df)
            .mark_rect()
            .encode(
                x=alt.X("date:T", title="Data", axis=alt.Axis(labelAngle=-45)),
                y=alt.Y("doctor_name:N", title="Medic"),
                color=alt.Color("shift_name:N", legend=alt.Legend(title="Tură")),
                tooltip=["date:T", "doctor_name", "shift_name"]
            )
            .properties(width="container", height=400)
        )
        st.altair_chart(chart, use_container_width=True)
    except Exception as e:
        st.warning(f"Nu am putut desena graficul Altair: {e}")


def main():
    st.title("🩺 Organizator de Gărzi – v2")

    # ─ Sidebar inputs
    with st.sidebar:
        st.header("📅 Interval")
        today = dt.date.today()
        start_date = st.date_input("Început", today)
        end_date = st.date_input("Sfârșit", today + dt.timedelta(days=30))
        shifts_per_day = st.number_input("Gărzi/zi", 1, 4, 1)
        st.markdown("---")

    # ─ Load data
    doctors_df = load_sheet("Doctors")
    schedule_df = load_sheet("Schedule")

    # display doctors
    st.subheader("👩‍⚕️ Medici")
    if doctors_df.empty:
        st.error("Lista medicilor e goală – adaugă în tab-ul 'Doctors' din Google Sheets.")
    else:
        st.dataframe(doctors_df, use_container_width=True)

    # generate schedule button
    if st.button("Generează orar", type="primary"):
        try:
            new_df = generate_round_robin(doctors_df["id"].tolist(), start_date, end_date, shifts_per_day)
            write_schedule(new_df)
            st.success("Orar salvat în Google Sheets!")
            schedule_df = new_df  # refresh local copy
        except Exception as e:
            st.error(str(e))

    # ─ Display schedule
    if schedule_df.empty:
        st.info("Încă nu există orar salvat.")
    else:
        show_schedule_table(schedule_df, doctors_df)


if __name__ == "__main__":
    main()
