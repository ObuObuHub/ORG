#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistem de Planificare Gărzi Medicale - Versiune Stabilă
Versiune: 10.0 - Doar componente Streamlit native pentru stabilitate maximă
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict
import calendar

# ──────────────────────────────────────────────────────────
# CONFIGURARE
# ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Planificare Gărzi Medicale",
    page_icon="🏥",
    layout="wide"
)

# Constante pentru coloane
COL_ID = "id"
COL_NAME = "name"
COL_SPEC = "speciality"
COL_MAX = "max_shifts_per_month"
COL_PHONE = "phone"
COL_EMAIL = "email"
COL_DATE = "date"
COL_SHIFT = "shift_name"
COL_DOC_ID = "doctor_id"

# Specialități disponibile
SPECIALTIES = [
    "ATI",
    "Urgențe", 
    "Chirurgie",
    "Medicină Internă",
    "Pediatrie",
    "Laborator",
    "Radiologie",
    "Altele"
]

# Tipuri de gărzi
SHIFT_TYPES = ["Gardă 24h", "Gardă Zi (08-20)", "Gardă Noapte (20-08)"]

# Zile săptămână
WEEKDAYS_RO = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']

# ──────────────────────────────────────────────────────────
# FUNCȚII PENTRU GOOGLE SHEETS
# ──────────────────────────────────────────────────────────

@st.cache_resource
def get_gsheet_client():
    """Creează și cache-uiește clientul Google Sheets."""
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Eroare conectare Google Sheets: {str(e)}")
        st.stop()

def get_sheet_id():
    """Obține ID-ul sheet-ului din configurare."""
    if "sheet_id" in st.secrets:
        return st.secrets["sheet_id"]
    else:
        st.error("Lipsește sheet_id în secrets.toml!")
        st.stop()

@st.cache_data(ttl=300)  # Cache pentru 5 minute
def load_data(sheet_name):
    """Încarcă date din Google Sheets cu error handling robust."""
    try:
        client = get_gsheet_client()
        sheet_id = get_sheet_id()
        sh = client.open_by_key(sheet_id)
        
        # Încearcă să obțină worksheet-ul
        try:
            worksheet = sh.worksheet(sheet_name)
            data = worksheet.get_all_records()
            
            if not data:
                return pd.DataFrame()
                
            df = pd.DataFrame(data)
            # Convertește coloanele goale în string gol
            df = df.fillna('')
            return df
            
        except gspread.exceptions.WorksheetNotFound:
            # Dacă foaia nu există, returnează DataFrame gol
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Eroare la încărcare date din {sheet_name}: {str(e)}")
        return pd.DataFrame()

def save_data(sheet_name, df):
    """Salvează date în Google Sheets cu error handling."""
    if df is None or df.empty:
        return
        
    try:
        client = get_gsheet_client()
        sheet_id = get_sheet_id()
        sh = client.open_by_key(sheet_id)
        
        # Încearcă să găsească sau să creeze worksheet-ul
        try:
            worksheet = sh.worksheet(sheet_name)
            worksheet.clear()
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)
        
        # Pregătește datele pentru salvare
        headers = df.columns.tolist()
        values = df.fillna('').astype(str).values.tolist()
        
        # Salvează datele
        if values:  # Doar dacă avem date
            worksheet.update([headers] + values, value_input_option='USER_ENTERED')
        else:
            worksheet.update([headers], value_input_option='USER_ENTERED')
            
        # Invalidate cache
        load_data.clear()
        
    except Exception as e:
        st.error(f"Eroare la salvare în {sheet_name}: {str(e)}")

# ──────────────────────────────────────────────────────────
# FUNCȚII PENTRU GESTIONAREA DATELOR
# ──────────────────────────────────────────────────────────

def clean_doctors_data(doctors_df):
    """Curăță și validează datele medicilor."""
    if doctors_df.empty:
        return doctors_df
        
    # Asigură că toate coloanele necesare există
    required_columns = [COL_ID, COL_NAME, COL_SPEC, COL_MAX]
    for col in required_columns:
        if col not in doctors_df.columns:
            doctors_df[col] = ''
    
    # Convertește ID-urile la numeric, elimină rândurile invalide
    doctors_df[COL_ID] = pd.to_numeric(doctors_df[COL_ID], errors='coerce')
    doctors_df = doctors_df.dropna(subset=[COL_ID])
    doctors_df[COL_ID] = doctors_df[COL_ID].astype(int)
    
    # Setează valori implicite pentru gărzi maxime
    doctors_df[COL_MAX] = pd.to_numeric(doctors_df[COL_MAX], errors='coerce').fillna(8).astype(int)
    
    return doctors_df

def get_doctor_name_map(doctors_df):
    """Creează mapping ID -> Nume pentru afișare."""
    if doctors_df.empty:
        return {}
    return dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))

# ──────────────────────────────────────────────────────────
# INTERFAȚĂ UTILIZATOR - VIZUALIZARE CALENDAR
# ──────────────────────────────────────────────────────────

def show_monthly_calendar(schedule_df, doctors_df, year, month):
    """Afișează calendar lunar folosind doar componente Streamlit."""
    
    st.subheader(f"📅 {calendar.month_name[month]} {year}")
    
    # Obține maparea numelor
    name_map = get_doctor_name_map(doctors_df)
    
    # Pregătește datele pentru luna selectată
    if not schedule_df.empty:
        schedule_df['date_parsed'] = pd.to_datetime(schedule_df[COL_DATE], errors='coerce')
        month_schedule = schedule_df[
            (schedule_df['date_parsed'].dt.year == year) & 
            (schedule_df['date_parsed'].dt.month == month)
        ]
    else:
        month_schedule = pd.DataFrame()
    
    # Obține structura calendarului pentru lună
    cal = calendar.monthcalendar(year, month)
    
    # Afișează header-ul cu zilele săptămânii
    days_header = st.columns(7)
    for i, day in enumerate(['Lun', 'Mar', 'Mie', 'Joi', 'Vin', 'Sâm', 'Dum']):
        with days_header[i]:
            if i >= 5:  # Weekend
                st.markdown(f"**:orange[{day}]**")
            else:
                st.markdown(f"**{day}**")
    
    # Afișează zilele
    for week in cal:
        week_cols = st.columns(7)
        for i, day in enumerate(week):
            if day > 0:
                with week_cols[i]:
                    # Container pentru zi
                    with st.container():
                        # Afișează ziua
                        if i >= 5:  # Weekend
                            st.markdown(f"**:orange[{day}]**")
                        else:
                            st.markdown(f"**{day}**")
                        
                        # Găsește gărzi pentru această zi
                        if not month_schedule.empty:
                            day_date = date(year, month, day)
                            day_shifts = month_schedule[
                                month_schedule['date_parsed'].dt.date == day_date
                            ]
                            
                            # Afișează gărzile
                            for _, shift in day_shifts.iterrows():
                                doc_name = name_map.get(shift[COL_DOC_ID], "?")
                                shift_type = shift[COL_SHIFT]
                                
                                # Folosește emoji pentru tipul de gardă
                                if "24h" in shift_type:
                                    emoji = "🔴"
                                elif "Zi" in shift_type:
                                    emoji = "🟢"
                                else:
                                    emoji = "🔵"
                                
                                # Afișează numele prescurtat
                                short_name = doc_name.split()[0] if doc_name != "?" else "?"
                                st.caption(f"{emoji} {short_name}")
            else:
                # Zi goală
                with week_cols[i]:
                    st.write("")

# ──────────────────────────────────────────────────────────
# INTERFAȚĂ UTILIZATOR - VIZUALIZARE GANTT SIMPLĂ
# ──────────────────────────────────────────────────────────

def show_simple_gantt(schedule_df, doctors_df, start_date, end_date):
    """Vizualizare Gantt simplă folosind dataframe-uri Streamlit."""
    
    if schedule_df.empty:
        st.info("Nu există gărzi programate pentru perioada selectată.")
        return
    
    # Pregătește datele
    schedule_df['date_parsed'] = pd.to_datetime(schedule_df[COL_DATE], errors='coerce')
    mask = (schedule_df['date_parsed'].dt.date >= start_date) & (schedule_df['date_parsed'].dt.date <= end_date)
    filtered = schedule_df[mask].copy()
    
    if filtered.empty:
        st.info("Nu există gărzi în perioada selectată.")
        return
    
    # Obține mapping nume
    name_map = get_doctor_name_map(doctors_df)
    
    # Creează un DataFrame pentru vizualizare
    # Vom crea un tabel cu medicii pe rânduri și datele pe coloane
    date_range = pd.date_range(start_date, end_date)
    gantt_data = {}
    
    # Inițializează cu string-uri goale
    for date_val in date_range:
        gantt_data[date_val.strftime('%d.%m')] = {}
    
    # Populează cu date
    for _, shift in filtered.iterrows():
        doc_name = name_map.get(shift[COL_DOC_ID], f"ID {shift[COL_DOC_ID]}")
        shift_date = shift['date_parsed'].strftime('%d.%m')
        shift_type = shift[COL_SHIFT]
        
        # Prescurtează tipul de gardă
        if "24h" in shift_type:
            shift_short = "24h"
        elif "Zi" in shift_type:
            shift_short = "Zi"
        else:
            shift_short = "Noapte"
        
        if shift_date in gantt_data:
            if doc_name not in gantt_data[shift_date]:
                gantt_data[shift_date][doc_name] = shift_short
            else:
                gantt_data[shift_date][doc_name] += f", {shift_short}"
    
    # Convertește în DataFrame pentru afișare
    if gantt_data:
        # Obține lista unică de medici
        all_doctors = set()
        for date_shifts in gantt_data.values():
            all_doctors.update(date_shifts.keys())
        
        # Creează DataFrame
        display_data = []
        for doc in sorted(all_doctors):
            row = {'Medic': doc}
            for date_str in gantt_data.keys():
                row[date_str] = gantt_data[date_str].get(doc, '')
            display_data.append(row)
        
        df_display = pd.DataFrame(display_data)
        
        # Afișează ca tabel
        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            height=min(600, len(all_doctors) * 35 + 100)
        )
        
        # Legendă
        st.caption("🔴 24h | 🟢 Zi (08-20) | 🔵 Noapte (20-08)")

# ──────────────────────────────────────────────────────────
# INTERFAȚĂ UTILIZATOR - VIZUALIZARE TABEL
# ──────────────────────────────────────────────────────────

def show_schedule_table(schedule_df, doctors_df, start_date, end_date):
    """Afișează programul ca tabel simplu."""
    
    if schedule_df.empty:
        st.info("Nu există gărzi programate.")
        return
    
    # Pregătește datele
    schedule_df['date_parsed'] = pd.to_datetime(schedule_df[COL_DATE], errors='coerce')
    mask = (schedule_df['date_parsed'].dt.date >= start_date) & (schedule_df['date_parsed'].dt.date <= end_date)
    filtered = schedule_df[mask].copy()
    
    if filtered.empty:
        st.info("Nu există gărzi în perioada selectată.")
        return
    
    # Mapping pentru nume și specialități
    name_map = get_doctor_name_map(doctors_df)
    spec_map = dict(zip(doctors_df[COL_ID], doctors_df[COL_SPEC])) if not doctors_df.empty else {}
    
    # Pregătește datele pentru afișare
    display_data = []
    for _, row in filtered.iterrows():
        display_data.append({
            'Data': row['date_parsed'].strftime('%d.%m.%Y'),
            'Zi': WEEKDAYS_RO[row['date_parsed'].weekday()],
            'Tip Gardă': row[COL_SHIFT],
            'Medic': name_map.get(row[COL_DOC_ID], f"ID {row[COL_DOC_ID]}"),
            'Specialitate': spec_map.get(row[COL_DOC_ID], '-')
        })
    
    # Sortează după dată
    df_display = pd.DataFrame(display_data)
    df_display = df_display.sort_values('Data')
    
    # Afișează tabelul
    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        height=min(600, len(df_display) * 35 + 100)
    )
    
    # Statistici
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Gărzi", len(df_display))
    with col2:
        unique_docs = filtered[COL_DOC_ID].nunique()
        st.metric("Medici Activi", unique_docs)
    with col3:
        weekend_count = sum(1 for d in display_data if d['Zi'] in ['Sâmbătă', 'Duminică'])
        st.metric("Gărzi Weekend", weekend_count)

# ──────────────────────────────────────────────────────────
# FUNCȚII PENTRU GENERARE PROGRAM
# ──────────────────────────────────────────────────────────

def generate_schedule(doctors_df, start_date, end_date, shift_types):
    """Generează program folosind algoritm round-robin simplu."""
    
    if doctors_df.empty:
        st.error("Nu există medici înregistrați!")
        return pd.DataFrame()
    
    if not shift_types:
        st.error("Selectează cel puțin un tip de gardă!")
        return pd.DataFrame()
    
    # Inițializare
    schedule_rows = []
    doctor_list = doctors_df[COL_ID].tolist()
    doctor_index = 0
    shifts_count = defaultdict(int)
    max_shifts = dict(zip(doctors_df[COL_ID], doctors_df[COL_MAX]))
    
    # Generare pentru fiecare zi
    current_date = start_date
    while current_date <= end_date:
        for shift_type in shift_types:
            # Găsește următorul medic disponibil
            attempts = 0
            assigned = False
            
            while attempts < len(doctor_list) and not assigned:
                doc_id = doctor_list[doctor_index % len(doctor_list)]
                month_key = f"{current_date.year}-{current_date.month}"
                
                # Verifică dacă nu a depășit limita lunară
                if shifts_count[f"{doc_id}_{month_key}"] < max_shifts.get(doc_id, 8):
                    # Atribuie garda
                    schedule_rows.append({
                        COL_DATE: current_date.strftime('%Y-%m-%d'),
                        COL_SHIFT: shift_type,
                        COL_DOC_ID: doc_id
                    })
                    shifts_count[f"{doc_id}_{month_key}"] += 1
                    assigned = True
                
                doctor_index += 1
                attempts += 1
            
            if not assigned:
                st.warning(f"Nu s-a putut aloca gardă pentru {current_date.strftime('%d.%m.%Y')} - {shift_type}")
        
        current_date += timedelta(days=1)
    
    return pd.DataFrame(schedule_rows)

# ──────────────────────────────────────────────────────────
# APLICAȚIA PRINCIPALĂ
# ──────────────────────────────────────────────────────────

def main():
    """Funcția principală a aplicației."""
    
    # Titlu și descriere
    st.title("🏥 Sistem de Planificare Gărzi Medicale")
    st.caption("Versiune simplificată și stabilă - folosind doar componente Streamlit native")
    
    # Încarcă datele
    with st.spinner("Se încarcă datele..."):
        doctors_df = load_data("Doctors")
        schedule_df = load_data("Schedule")
        
        # Curăță datele medicilor
        doctors_df = clean_doctors_data(doctors_df)
    
    # Sidebar pentru navigare și acțiuni
    with st.sidebar:
        st.header("🔧 Meniu Principal")
        
        # Selectare vizualizare
        view_mode = st.radio(
            "Mod Vizualizare:",
            ["📅 Calendar Lunar", "📊 Tabel Gantt", "📋 Listă Detaliată"],
            index=0
        )
        
        st.divider()
        
        # Secțiune Manager (simplificată - fără autentificare)
        with st.expander("👨‍💼 Funcții Administrative"):
            
            # Generare automată
            st.subheader("Generare Automată")
            
            col1, col2 = st.columns(2)
            with col1:
                gen_start = st.date_input("De la:", value=date.today())
            with col2:
                gen_end = st.date_input("Până la:", value=date.today() + timedelta(days=30))
            
            selected_shifts = st.multiselect(
                "Tipuri de gărzi:",
                options=SHIFT_TYPES,
                default=["Gardă 24h"]
            )
            
            if st.button("🚀 Generează", type="primary", use_container_width=True):
                if gen_start <= gen_end:
                    new_schedule = generate_schedule(doctors_df, gen_start, gen_end, selected_shifts)
                    if not new_schedule.empty:
                        save_data("Schedule", new_schedule)
                        st.success("✅ Program generat cu succes!")
                        st.rerun()
                else:
                    st.error("Data de început trebuie să fie înainte de data de sfârșit!")
            
            # Ștergere program
            st.divider()
            if st.button("🗑️ Șterge Tot Programul", type="secondary", use_container_width=True):
                if st.checkbox("Confirmă ștergerea"):
                    save_data("Schedule", pd.DataFrame())
                    st.success("Program șters!")
                    st.rerun()
        
        # Export
        st.divider()
        if not schedule_df.empty:
            # Generează conținut pentru export
            export_lines = ["PROGRAM GĂRZI MEDICALE", "=" * 40, ""]
            export_lines.append(f"Generat: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
            export_lines.append("")
            
            # Sortează și formatează
            name_map = get_doctor_name_map(doctors_df)
            schedule_df['date_parsed'] = pd.to_datetime(schedule_df[COL_DATE], errors='coerce')
            schedule_sorted = schedule_df.sort_values('date_parsed')
            
            for _, row in schedule_sorted.iterrows():
                date_str = row['date_parsed'].strftime('%d.%m.%Y')
                weekday = WEEKDAYS_RO[row['date_parsed'].weekday()]
                doctor = name_map.get(row[COL_DOC_ID], f"ID {row[COL_DOC_ID]}")
                shift = row[COL_SHIFT]
                
                export_lines.append(f"{weekday}, {date_str}: {shift} - {doctor}")
            
            export_content = "\n".join(export_lines)
            
            st.download_button(
                label="📥 Descarcă Program (.txt)",
                data=export_content,
                file_name=f"program_garzi_{date.today()}.txt",
                mime="text/plain",
                use_container_width=True
            )
    
    # Zona principală de conținut
    if view_mode == "📅 Calendar Lunar":
        # Selector lună și an
        col1, col2, col3 = st.columns([2, 2, 6])
        with col1:
            selected_month = st.selectbox(
                "Luna:",
                range(1, 13),
                index=date.today().month - 1,
                format_func=lambda x: calendar.month_name[x]
            )
        with col2:
            selected_year = st.selectbox(
                "An:",
                range(2024, 2027),
                index=date.today().year - 2024
            )
        
        # Afișează calendarul
        show_monthly_calendar(schedule_df, doctors_df, selected_year, selected_month)
        
    elif view_mode == "📊 Tabel Gantt":
        st.subheader("📊 Vizualizare Tip Gantt")
        
        # Selector perioadă
        col1, col2 = st.columns(2)
        with col1:
            gantt_start = st.date_input("De la:", value=date.today())
        with col2:
            gantt_end = st.date_input("Până la:", value=date.today() + timedelta(days=14))
        
        # Afișează Gantt
        show_simple_gantt(schedule_df, doctors_df, gantt_start, gantt_end)
        
    else:  # Listă Detaliată
        st.subheader("📋 Listă Detaliată Gărzi")
        
        # Selector perioadă
        col1, col2 = st.columns(2)
        with col1:
            table_start = st.date_input("De la:", value=date.today())
        with col2:
            table_end = st.date_input("Până la:", value=date.today() + timedelta(days=30))
        
        # Afișează tabelul
        show_schedule_table(schedule_df, doctors_df, table_start, table_end)
    
    # Tab pentru gestionare personal
    with st.expander("👥 Gestionare Personal Medical"):
        st.subheader("Listă Personal")
        
        # Editor pentru personal
        if doctors_df.empty:
            # DataFrame gol cu structura corectă
            doctors_df = pd.DataFrame({
                COL_ID: [1],
                COL_NAME: ["Exemplu Doctor"],
                COL_SPEC: ["Urgențe"],
                COL_MAX: [8],
                COL_PHONE: ["0700000000"],
                COL_EMAIL: ["doctor@spital.ro"]
            })
        
        # Afișează editor
        edited_df = st.data_editor(
            doctors_df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                COL_ID: st.column_config.NumberColumn(
                    "ID",
                    help="ID unic pentru fiecare medic",
                    min_value=1,
                    required=True
                ),
                COL_NAME: st.column_config.TextColumn(
                    "Nume Complet",
                    help="Numele complet al medicului",
                    required=True
                ),
                COL_SPEC: st.column_config.SelectboxColumn(
                    "Specialitate",
                    help="Specialitatea medicului",
                    options=SPECIALTIES,
                    required=True
                ),
                COL_MAX: st.column_config.NumberColumn(
                    "Max Gărzi/Lună",
                    help="Numărul maxim de gărzi pe lună",
                    min_value=1,
                    max_value=20,
                    default=8
                ),
                COL_PHONE: "Telefon",
                COL_EMAIL: "Email"
            }
        )
        
        # Buton salvare
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("💾 Salvează", type="primary", use_container_width=True):
                # Validare
                if edited_df[COL_ID].duplicated().any():
                    st.error("❌ Există ID-uri duplicate! Fiecare medic trebuie să aibă un ID unic.")
                else:
                    save_data("Doctors", edited_df)
                    st.success("✅ Lista personalului a fost salvată!")
                    st.rerun()

# Rulare aplicație
if __name__ == "__main__":
    main()
