"""streamlit_guard_scheduler.py
Streamlit app for managing hospital on‑call (garda) rosters powered by Google Sheets.

Prerequisites
-------------
1. Create a Google Cloud project and service‑account with access to the target spreadsheet.
2. In Streamlit Cloud (or locally), add the service‑account JSON *as secrets*:
   [gcp_service_account]
   type = "service_account"
   project_id = "..."
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\\n..."
   client_email = "..."
   client_id = "..."
   ...
3. Also add the spreadsheet ID to *secrets*:
   sheet_id = "YOUR_SHEET_ID"
4. Required Python packages (add to requirements.txt):
   streamlit
   pandas
   gspread
   google-auth

Google Sheets layout
--------------------
The spreadsheet should contain (at minimum) two tabs:

1. `Doctors`
   | id | name        | speciality | max_shifts_per_month |
   |----|-------------|------------|----------------------|
   | 1  | Dr. Popescu | Hematology | 6                    |

2. `Schedule`
   | date       | shift_name | doctor_id |
   |------------|------------|-----------|
   | 2025-07-01 | Night      | 1         |

Feel free to add more sheets (Preferences, Holidays, etc.).

"""

from __future__ import annotations

import datetime as dt
from typing import List

import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
import gspread


@st.cache_resource
def get_gsheet_client():
    """Authorize and return a gspread client using Streamlit secrets."""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scope
    )
    return gspread.authorize(creds)


@st.cache_data(ttl=300)
def load_sheet(sheet_name: str) -> pd.DataFrame:
    """Load a Google Sheet tab into a DataFrame."""
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    worksheet = sh.worksheet(sheet_name)
    df = pd.DataFrame(worksheet.get_all_records())
    return df


def write_schedule(df: pd.DataFrame):
    """Write the schedule DataFrame back to the Schedule sheet, replacing contents."""
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    worksheet = sh.worksheet("Schedule")
    # Clear existing rows and update
    worksheet.clear()
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())


def generate_round_robin(
    doctors: List[int], start_date: dt.date, end_date: dt.date, shifts_per_day: int = 1
) -> pd.DataFrame:
    """Simple round‑robin scheduler.

    Args:
        doctors: list of doctor_id
        start_date: first day inclusive
        end_date: last day inclusive
        shifts_per_day: number of identical shifts per day (e.g., 1 = full 24h garda)
    Returns:
        DataFrame with columns date, shift_name, doctor_id
    """
    schedule_rows = []
    total_days = (end_date - start_date).days + 1
    doctor_cycle = doctors * ((total_days * shifts_per_day) // len(doctors) + 1)
    idx = 0
    for n in range(total_days):
        day = start_date + dt.timedelta(days=n)
        for spd in range(shifts_per_day):
            schedule_rows.append(
                {
                    "date": day.isoformat(),
                    "shift_name": f"Shift {spd+1}",
                    "doctor_id": doctor_cycle[idx],
                }
            )
            idx += 1
    return pd.DataFrame(schedule_rows)


def main():
    st.title("🩺 Organizator de Gărzi")

    st.sidebar.header("📅 Interval de programare")
    today = dt.date.today()
    col1, col2 = st.sidebar.columns(2)
    with col1:
        start_date = st.date_input("Început", today)
    with col2:
        end_date = st.date_input("Sfârșit", today + dt.timedelta(days=30))

    st.sidebar.markdown("---")
    shifts_per_day = st.sidebar.number_input(
        "Gărzi/zi", min_value=1, max_value=5, value=1
    )

    # Load data
    doctors_df = load_sheet("Doctors")

    st.subheader("👩‍⚕️ Lista Medicilor")
    st.dataframe(doctors_df, use_container_width=True)

    doctor_ids = doctors_df["id"].tolist()

    if start_date > end_date:
        st.error("Data de început trebuie să fie înainte de data de sfârșit.")
        st.stop()

    if st.button("Generează orar", type="primary"):
        schedule_df = generate_round_robin(
            doctor_ids, start_date, end_date, shifts_per_day
        )
        write_schedule(schedule_df)
        st.success("Orarul a fost salvat în Google Sheets! 🚀")

    st.subheader("📊 Orar curent (din Google Sheets)")
    schedule_df = load_sheet("Schedule")
    if not schedule_df.empty:
        st.dataframe(schedule_df, use_container_width=True)
    else:
        st.info("Nu există încă un orar salvat. Folosește butonul de mai sus.")


if __name__ == "__main__":
    main()
