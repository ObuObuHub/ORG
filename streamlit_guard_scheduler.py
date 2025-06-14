"""streamlit_guard_scheduler.py
Streamlit app for managing hospital on‑call (garda) rosters via Google Sheets
and visualising the schedule in Streamlit.

2025‑06‑14 v2.2
────────────────
• FIX syntax – removed extra parenthesis & bad indentation → no more SyntaxError.
• Refactored `show_schedule()` for clarity.
• Rest of the behaviour unchanged (auto‑create sheets, optional formatting gracefully handled).
"""
from __future__ import annotations

import datetime as dt
from typing import List, Dict

import altair as alt
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
import gspread
from gspread.utils import rowcol_to_a1

# ──────────────────────────────────────────────────────────
# Optional Google‑Sheets formatting (fails gracefully)
# ──────────────────────────────────────────────────────────
try:
    from gspread_formatting import (
        CellFormat,
        Color,
        set_frozen,
        conditional_format,
        BooleanRule,
    )
    _FMT_AVAILABLE = True
except ImportError:  # library absent – define NO‑OP stubs
    _FMT_AVAILABLE = False

    def set_frozen(ws, rows=1, cols=0):  # type: ignore
        return None

    def conditional_format(*args, **kwargs):  # type: ignore
        return None

    class Color:  # type: ignore
        def __init__(self, r=1, g=1, b=1):
            pass

    class BooleanRule:  # type: ignore
        pass

# ──────────────────────────────────────────────────────────
# Google‑Sheets helpers
# ──────────────────────────────────────────────────────────
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
    """Ensure a worksheet exists with the given headers and basic formatting."""
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=str(rows), cols=str(cols))

    if not any(ws.row_values(1)):
        ws.update([headers])

    if _FMT_AVAILABLE:
        set_frozen(ws, rows=1)
        first_col = rowcol_to_a1(1, 1)[0]
        last_col = rowcol_to_a1(1, len(headers))[0]
        rng = f"{first_col}2:{last_col}{rows}"
        conditional_format(
            ws,
            rng,
            BooleanRule(
                condition={
                    "type": "CUSTOM_FORMULA",
                    "values": [{"userEnteredValue": "=ISEVEN(ROW())"}],
                },
                format=CellFormat(backgroundColor=Color(0.95, 0.95, 0.95)),
            ),
        )
    return ws


@st.cache_data(ttl=300)
def load_sheet(sheet_name: str) -> pd.DataFrame:
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])

    if sheet_name == "Doctors":
        ws = ensure_worksheet(sh, "Doctors", ["id", "name", "speciality", "max_shifts_per_month"])
    else:
        ws = ensure_worksheet(sh, "Schedule", ["date", "shift_name", "doctor_id"])

    return pd.DataFrame(ws.get_all_records())


def write_schedule(df: pd.DataFrame):
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    ws = ensure_worksheet(sh, "Schedule", ["date", "shift_name", "doctor_id"])
    ws.clear()
    ws.update([df.columns.values.tolist()] + df.values.tolist())
    if _FMT_AVAILABLE:
        set_frozen(ws, rows=1)

# ──────────────────────────────────────────────────────────
# Scheduler logic
# ──────────────────────────────────────────────────────────

def generate_round_robin(doctors: List[int], start: dt.date, end: dt.date, shifts_per_day: int = 1) -> pd.DataFrame:
    if not doctors:
        raise ValueError("Lista medicilor este goală – adaugă cel puțin un medic în tab‑ul 'Doctors'.")

    num_days = (end - start).days + 1
    doctor_cycle = doctors * ((num_days * shifts_per_day) // len(doctors) + 1)

    rows: List[Dict] = []
    idx = 0
    for n in range(num_days):
        cur_date = start + dt.timedelta(days=n)
        for s in range(shifts_per_day):
            rows.append(
                {
                    "date": cur_date.isoformat(),
                    "shift_name": f"Shift {s+1}",
                    "doctor_id": doctor_cycle[idx],
                }
            )
            idx += 1
    return pd.DataFrame(rows)

# ──────────────────────────────────────────────────────────
# UI helpers
# ──────────────────────────────────────────────────────────

def show_schedule(schedule_df: pd.DataFrame, doctors_df: pd.DataFrame):
    """Display table + heat‑map for the current schedule."""
    # Map ID→Name
    id2name = doctors_df.set_index("id")["name"].to_dict()
    df = schedule_df.copy()
    df["doctor_name"] = df["doctor_id"].map(id2name)

    # Pivot table
    st.subheader("📅 Calendar (pivot)")
    pivot = df.pivot(index="date", columns="shift_name", values="doctor_name")
    st.dataframe(pivot, use_container_width=True)

    # Heat‑map grid
    st.subheader("🖼️ Vizualizare grafică")
    df["date_str"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    chart = (
        alt.Chart(df)
        .mark_rect()
        .encode(
            x=alt.X("date_str:O", title="Data", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("doctor_name:N", title="Medic"),
            color=alt.Color("shift_name:N", legend=alt.Legend(title="Tură")),
            tooltip=["date_str", "doctor_name", "shift_name"],
        )
        .properties(width="container", height=500)
    )
    st.altair_chart(chart, use_container_width=True)

# ──────────────────────────────────────────────────────────
# Main Streamlit app
# ──────────────────────────────────────────────────────────

def main():
    st.title("🩺 Organizator de Gărzi – v2.2")

    # Sidebar controls
    with st.sidebar:
        st.header("📅 Interval")
        today = dt.date.today()
        start_date = st.date_input("Început", today)
        end_date = st.date_input("Sfârșit", today + dt.timedelta(days=30))
        shifts_per_day = st.number_input("Gărzi/zi", 1, 4, 1)
        st.markdown("---")

    # Load data
    doctors_df = load_sheet("Doctors")
    schedule_df = load_sheet("Schedule")

    # Doctors table
    st.subheader("👩‍⚕️ Medici")
    if doctors_df.empty:
        st.warning("Lista medicilor e goală – completează tab‑ul 'Doctors' în Google Sheets.")
    else:
        st.dataframe(doctors_df, use_container_width=True)

    # Generate schedule
    if st.button("Generează orar", type="primary"):
        try:
            new_df = generate_round_robin(
                doctors_df["id"].tolist(), start_date, end_date, shifts_per_day
            )
            write_schedule(new_df)
            schedule_df = new_df  # refresh local copy
            st.success("Orar salvat și afișat mai jos!")
        except Exception as e:
            st.error(str(e))

    # Display schedule
    if not schedule_df.empty:
        show_schedule(schedule_df, doctors_df)
    else:
        st.info("Încă nu există orar salvat.")


if __name__ == "__main__":
    main()
