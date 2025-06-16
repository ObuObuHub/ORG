#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistem Simplificat de Planificare Gărzi Medicale
Versiune: 9.0 - Design inspirat din aplicații medicale de succes
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
# CONFIGURARE ȘI CONSTANTE
# ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🏥 Planificare Gărzi Medicale",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Nume foi în Google Sheets
SHEET_DOCTORS = "Doctors"
SHEET_SCHEDULE = "Schedule"
SHEET_UNAVAILABLE = "Unavailable"

# Coloane principale
COL_ID = "id"
COL_NAME = "name"
COL_SPEC = "speciality"
COL_MAX = "max_shifts_per_month"
COL_PHONE = "phone"
COL_EMAIL = "email"
COL_DATE = "date"
COL_SHIFT = "shift_name"
COL_DOC_ID = "doctor_id"

# Specialități
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

# Tipuri de ture cu coduri de culoare
SHIFT_CONFIGS = {
    "Gardă 24h": {"color": "#DC3545", "icon": "🔴", "hours": 24},
    "Gardă Zi (08-20)": {"color": "#28A745", "icon": "🟢", "hours": 12},
    "Gardă Noapte (20-08)": {"color": "#17A2B8", "icon": "🔵", "hours": 12}
}

# Zile săptămână în română
WEEKDAYS_RO = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']

# Parola manager pentru funcții administrative
MANAGER_PASSWORD = "admin123"

# ──────────────────────────────────────────────────────────
# Inițializare Session State
# ──────────────────────────────────────────────────────────
def init_session_state():
    """Inițializează toate variabilele de sesiune necesare."""
    if 'schedule_data' not in st.session_state:
        st.session_state.schedule_data = pd.DataFrame()
    if 'selected_user' not in st.session_state:
        st.session_state.selected_user = None
    if 'user_role' not in st.session_state:
        st.session_state.user_role = 'viewer'
    if 'view_mode' not in st.session_state:
        st.session_state.view_mode = 'calendar'
    if 'selected_month' not in st.session_state:
        st.session_state.selected_month = date.today().month
    if 'selected_year' not in st.session_state:
        st.session_state.selected_year = date.today().year

# ──────────────────────────────────────────────────────────
# Funcții pentru configurare spitale
# ──────────────────────────────────────────────────────────
def get_hospital_config():
    """Returnează configurația spitalelor."""
    if "hospitals" in st.secrets:
        return st.secrets["hospitals"].to_dict()
    elif "sheet_id" in st.secrets:
        return {
            "default": {
                "name": "Spital Principal",
                "sheet_id": st.secrets["sheet_id"]
            }
        }
    else:
        st.error("❌ Lipsește configurația în secrets.toml!")
        st.stop()

# ──────────────────────────────────────────────────────────
# Funcții Google Sheets cu caching
# ──────────────────────────────────────────────────────────
@st.cache_resource
def get_gsheet_client():
    """Creează clientul Google Sheets cu caching."""
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Eroare conectare: {str(e)}")
        st.stop()

@st.cache_data(ttl=60)  # Cache pentru 1 minut
def load_data(sheet_name, sheet_id):
    """Încarcă date din foaia specificată cu caching."""
    try:
        client = get_gsheet_client()
        sh = client.open_by_key(sheet_id)
        
        try:
            worksheet = sh.worksheet(sheet_name)
            data = worksheet.get_all_records()
            if not data:
                return pd.DataFrame()
            return pd.DataFrame(data)
        except:
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"❌ Eroare încărcare date: {str(e)}")
        return pd.DataFrame()

def save_data(sheet_name, df, sheet_id):
    """Salvează date în foaia specificată."""
    if df is None:
        return
    
    try:
        client = get_gsheet_client()
        sh = client.open_by_key(sheet_id)
        
        try:
            worksheet = sh.worksheet(sheet_name)
            worksheet.clear()
        except:
            worksheet = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)
        
        if not df.empty:
            headers = df.columns.tolist()
            values = df.fillna('').astype(str).values.tolist()
            data = [headers] + values
            worksheet.update(data, value_input_option='USER_ENTERED')
            
        # Invalidate cache after save
        load_data.clear()
            
    except Exception as e:
        st.error(f"❌ Eroare salvare: {str(e)}")

# ──────────────────────────────────────────────────────────
# Selector simplu pentru utilizatori (fără login)
# ──────────────────────────────────────────────────────────
def create_user_selector(doctors_df):
    """Creează selector pentru utilizatori fără autentificare."""
    with st.sidebar:
        st.markdown("### 👤 Selectează Utilizator")
        
        # Rol utilizator
        role = st.selectbox(
            "Tip utilizator:",
            ["Vizualizare", "Medic", "Manager"],
            help="Selectează rolul pentru a accesa funcționalitățile"
        )
        
        if role == "Manager":
            password = st.text_input("Parolă manager:", type="password")
            if password == MANAGER_PASSWORD:
                st.session_state.user_role = 'manager'
                st.success("✅ Acces manager activat")
            else:
                st.session_state.user_role = 'viewer'
                if password:
                    st.error("❌ Parolă incorectă")
        elif role == "Medic":
            st.session_state.user_role = 'doctor'
            
            # Selector medic cu filtrare
            if not doctors_df.empty:
                # Filtrare după specialitate
                specialities = ["Toate"] + doctors_df[COL_SPEC].unique().tolist()
                selected_spec = st.selectbox("Specialitate:", specialities)
                
                # Filtrare medici
                if selected_spec == "Toate":
                    filtered_doctors = doctors_df
                else:
                    filtered_doctors = doctors_df[doctors_df[COL_SPEC] == selected_spec]
                
                # Selector medic
                doctor_options = dict(zip(
                    filtered_doctors[COL_NAME] + " - " + filtered_doctors[COL_SPEC],
                    filtered_doctors[COL_ID]
                ))
                
                if doctor_options:
                    selected = st.selectbox(
                        "Selectează numele tău:",
                        list(doctor_options.keys())
                    )
                    st.session_state.selected_user = {
                        'id': doctor_options[selected],
                        'name': selected.split(" - ")[0],
                        'role': 'doctor'
                    }
                else:
                    st.warning("Nu există medici în această specialitate")
        else:
            st.session_state.user_role = 'viewer'
            st.session_state.selected_user = None

# ──────────────────────────────────────────────────────────
# Vizualizare Calendar Principal
# ──────────────────────────────────────────────────────────
def show_calendar_view(schedule_df, doctors_df, selected_month, selected_year):
    """Afișează calendar lunar cu gărzi."""
    # Mapare ID -> Nume
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    
    # Selector lună/an
    col1, col2, col3 = st.columns([2, 2, 8])
    with col1:
        month = st.selectbox(
            "Luna:",
            range(1, 13),
            index=selected_month - 1,
            format_func=lambda x: calendar.month_name[x]
        )
    with col2:
        year = st.selectbox(
            "An:",
            range(2024, 2027),
            index=selected_year - 2024
        )
    
    # Actualizează session state
    st.session_state.selected_month = month
    st.session_state.selected_year = year
    
    # Calendar
    cal = calendar.monthcalendar(year, month)
    
    # CSS pentru calendar
    st.markdown("""
    <style>
    .calendar-container {
        background: white;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .calendar-day {
        border: 1px solid #e0e0e0;
        padding: 10px;
        min-height: 100px;
        background: white;
        border-radius: 5px;
        margin: 2px;
    }
    .calendar-weekend {
        background: #fff3cd !important;
    }
    .calendar-header {
        font-weight: bold;
        text-align: center;
        padding: 10px;
        background: #f8f9fa;
        border-radius: 5px;
    }
    .shift-badge {
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 12px;
        margin: 2px;
        display: inline-block;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Header zile
    st.markdown('<div class="calendar-container">', unsafe_allow_html=True)
    cols = st.columns(7)
    for i, day_name in enumerate(['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']):
        with cols[i]:
            st.markdown(f'<div class="calendar-header">{day_name}</div>', unsafe_allow_html=True)
    
    # Zile calendar
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day > 0:
                day_date = date(year, month, day)
                is_weekend = i >= 5
                
                with cols[i]:
                    # Container pentru zi
                    day_class = "calendar-day calendar-weekend" if is_weekend else "calendar-day"
                    
                    # Găsește gărzi pentru această zi
                    if not schedule_df.empty:
                        day_schedule = schedule_df[
                            pd.to_datetime(schedule_df[COL_DATE]).dt.date == day_date
                        ]
                    else:
                        day_schedule = pd.DataFrame()
                    
                    # Afișare zi
                    st.markdown(f'<div class="{day_class}">', unsafe_allow_html=True)
                    st.markdown(f"**{day}**")
                    
                    # Afișare gărzi
                    if not day_schedule.empty:
                        for _, shift in day_schedule.iterrows():
                            doc_name = id_to_name.get(shift[COL_DOC_ID], "?")
                            shift_config = SHIFT_CONFIGS.get(shift[COL_SHIFT], {})
                            icon = shift_config.get('icon', '⚪')
                            
                            st.markdown(f"{icon} {doc_name[:15]}")
                    
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                with cols[i]:
                    st.write("")
    
    st.markdown('</div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────
# Vizualizare Gantt cu Streamlit nativ
# ──────────────────────────────────────────────────────────
def show_gantt_view(schedule_df, doctors_df, start_date, end_date):
    """Afișează programul ca diagramă Gantt folosind componente Streamlit native."""
    if schedule_df.empty:
        st.info("📅 Nu există program generat pentru perioada selectată.")
        return
    
    # Mapare ID -> Nume
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    
    # Filtrare date pentru perioada selectată
    schedule_df = schedule_df.copy()
    schedule_df['date_obj'] = pd.to_datetime(schedule_df[COL_DATE])
    mask = (schedule_df['date_obj'].dt.date >= start_date) & (schedule_df['date_obj'].dt.date <= end_date)
    filtered = schedule_df[mask]
    
    if filtered.empty:
        st.info("Nu există gărzi în perioada selectată.")
        return
    
    # Obține lista unică de medici din perioada selectată
    unique_doctors = filtered[COL_DOC_ID].unique()
    doctor_names = [id_to_name.get(doc_id, f"ID {doc_id}") for doc_id in unique_doctors]
    
    # Calculează numărul de zile
    date_range = pd.date_range(start_date, end_date)
    num_days = len(date_range)
    
    # CSS pentru Gantt
    st.markdown("""
    <style>
    .gantt-container {
        background: white;
        border-radius: 8px;
        padding: 10px;
        overflow-x: auto;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .gantt-header {
        display: grid;
        grid-template-columns: 150px repeat(""" + str(num_days) + """, 80px);
        border-bottom: 2px solid #333;
        font-weight: bold;
        position: sticky;
        top: 0;
        background: white;
        z-index: 10;
    }
    .gantt-row {
        display: grid;
        grid-template-columns: 150px repeat(""" + str(num_days) + """, 80px);
        border-bottom: 1px solid #eee;
        min-height: 40px;
        align-items: center;
    }
    .gantt-cell {
        padding: 5px;
        border-right: 1px solid #f0f0f0;
        text-align: center;
        position: relative;
    }
    .gantt-name {
        font-weight: bold;
        text-align: left;
        background: #f8f9fa;
        position: sticky;
        left: 0;
        z-index: 5;
    }
    .gantt-weekend {
        background: #fff3cd;
    }
    .shift-block {
        padding: 2px 4px;
        border-radius: 4px;
        font-size: 11px;
        color: white;
        margin: 1px;
    }
    .shift-24h {
        background: #DC3545;
    }
    .shift-day {
        background: #28A745;
    }
    .shift-night {
        background: #17A2B8;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Construiește tabelul Gantt
    st.markdown('<div class="gantt-container">', unsafe_allow_html=True)
    
    # Header cu datele
    header_html = '<div class="gantt-header">'
    header_html += '<div class="gantt-cell gantt-name">Personal Medical</div>'
    
    for d in date_range:
        weekday = WEEKDAYS_RO[d.weekday()]
        weekend_class = "gantt-weekend" if d.weekday() >= 5 else ""
        header_html += f'''
        <div class="gantt-cell {weekend_class}">
            <div>{d.day}.{d.month}</div>
            <div style="font-size: 10px; color: #666;">{weekday[:3]}</div>
        </div>
        '''
    header_html += '</div>'
    st.markdown(header_html, unsafe_allow_html=True)
    
    # Rânduri pentru fiecare medic
    for doc_id, doc_name in zip(unique_doctors, doctor_names):
        row_html = '<div class="gantt-row">'
        row_html += f'<div class="gantt-cell gantt-name">{doc_name}</div>'
        
        # Pentru fiecare zi
        for d in date_range:
            weekend_class = "gantt-weekend" if d.weekday() >= 5 else ""
            
            # Găsește gărzile pentru acest medic în această zi
            day_shifts = filtered[
                (filtered[COL_DOC_ID] == doc_id) & 
                (filtered['date_obj'].dt.date == d.date())
            ]
            
            row_html += f'<div class="gantt-cell {weekend_class}">'
            
            for _, shift in day_shifts.iterrows():
                shift_type = shift[COL_SHIFT]
                
                # Determină clasa CSS și textul
                if "24h" in shift_type:
                    shift_class = "shift-24h"
                    display_text = "24h"
                elif "Zi" in shift_type:
                    shift_class = "shift-day"
                    display_text = "08-20"
                else:
                    shift_class = "shift-night"
                    display_text = "20-08"
                
                row_html += f'<div class="shift-block {shift_class}">{display_text}</div>'
            
            row_html += '</div>'
        
        row_html += '</div>'
        st.markdown(row_html, unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Legendă
    st.markdown("""
    <div style="margin-top: 20px; padding: 10px; background: #f8f9fa; border-radius: 5px;">
        <strong>Legendă:</strong>
        <span class="shift-block shift-24h" style="display: inline-block; margin: 0 10px;">Gardă 24h</span>
        <span class="shift-block shift-day" style="display: inline-block; margin: 0 10px;">Gardă Zi</span>
        <span class="shift-block shift-night" style="display: inline-block; margin: 0 10px;">Gardă Noapte</span>
        <span style="background: #fff3cd; padding: 2px 8px; margin: 0 10px; border: 1px solid #ddd; display: inline-block;">Weekend</span>
    </div>
    """, unsafe_allow_html=True)
    
    # Statistici pentru perioada selectată
    st.divider()
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_shifts = len(filtered)
        st.metric("Total Gărzi", total_shifts)
    
    with col2:
        unique_docs_period = filtered[COL_DOC_ID].nunique()
        st.metric("Medici Activi", unique_docs_period)
    
    with col3:
        # Calculează distribuția pe tipuri de gărzi
        shift_distribution = filtered[COL_SHIFT].value_counts()
        most_common = shift_distribution.index[0] if not shift_distribution.empty else "N/A"
        st.metric("Tip Gardă Predominant", most_common.split('(')[0])

# ──────────────────────────────────────────────────────────
# Vizualizare Tabel Simplu
# ──────────────────────────────────────────────────────────
def show_table_view(schedule_df, doctors_df, start_date, end_date):
    """Afișează programul ca tabel simplu și clar."""
    if schedule_df.empty:
        st.info("📅 Nu există program generat.")
        return
    
    # Mapare ID -> Nume
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    id_to_spec = dict(zip(doctors_df[COL_ID], doctors_df[COL_SPEC]))
    
    # Filtrare și pregătire date
    schedule_df = schedule_df.copy()
    schedule_df['date_obj'] = pd.to_datetime(schedule_df[COL_DATE])
    
    # Filtrare pentru perioada selectată
    mask = (schedule_df['date_obj'].dt.date >= start_date) & (schedule_df['date_obj'].dt.date <= end_date)
    filtered = schedule_df[mask].copy()
    
    if filtered.empty:
        st.info("Nu există gărzi în perioada selectată.")
        return
    
    # Adaugă informații suplimentare
    filtered['Medic'] = filtered[COL_DOC_ID].map(id_to_name)
    filtered['Specialitate'] = filtered[COL_DOC_ID].map(id_to_spec)
    filtered['Data'] = filtered['date_obj'].dt.strftime('%d.%m.%Y')
    filtered['Zi'] = filtered['date_obj'].apply(lambda x: WEEKDAYS_RO[x.weekday()])
    filtered['Weekend'] = filtered['date_obj'].dt.weekday >= 5
    
    # Sortare după dată
    filtered = filtered.sort_values('date_obj')
    
    # Afișare tabel stilizat
    for _, row in filtered.iterrows():
        col1, col2, col3, col4, col5 = st.columns([1, 2, 2, 2, 3])
        
        with col1:
            if row['Weekend']:
                st.markdown(f"**🟡 {row['Zi'][:3]}**")
            else:
                st.write(row['Zi'][:3])
        
        with col2:
            st.write(row['Data'])
        
        with col3:
            shift_config = SHIFT_CONFIGS.get(row[COL_SHIFT], {})
            icon = shift_config.get('icon', '⚪')
            st.write(f"{icon} {row[COL_SHIFT].split('(')[0]}")
        
        with col4:
            st.write(row['Specialitate'])
        
        with col5:
            st.write(f"**{row['Medic']}**")
        
        st.divider()
    
    # Statistici rezumat
    st.subheader("📊 Rezumat Perioadă")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Gărzi", len(filtered))
    
    with col2:
        weekend_count = len(filtered[filtered['Weekend']])
        st.metric("Gărzi Weekend", weekend_count)
    
    with col3:
        unique_docs = filtered[COL_DOC_ID].nunique()
        st.metric("Medici Activi", unique_docs)

# ──────────────────────────────────────────────────────────
# Funcții pentru Manager - Alocare simplă
# ──────────────────────────────────────────────────────────
def show_manager_allocation(schedule_df, doctors_df, unavail_df):
    """Interfață simplă pentru alocare manuală de gărzi."""
    st.subheader("🔧 Alocare Manuală Gărzi")
    
    # Formular pentru adăugare gardă
    with st.form("add_shift_form"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            shift_date = st.date_input("Data:", value=date.today())
        
        with col2:
            shift_type = st.selectbox("Tip gardă:", list(SHIFT_CONFIGS.keys()))
        
        with col3:
            # Filtrare medici disponibili
            available_doctors = get_available_doctors(doctors_df, unavail_df, shift_date)
            
            if available_doctors:
                doctor_options = {
                    f"{doc[COL_NAME]} - {doc[COL_SPEC]}": doc[COL_ID]
                    for _, doc in available_doctors.iterrows()
                }
                
                selected_doc_display = st.selectbox(
                    "Medic:",
                    list(doctor_options.keys())
                )
                selected_doc_id = doctor_options[selected_doc_display]
            else:
                st.warning("Nu există medici disponibili pentru această dată")
                selected_doc_id = None
        
        submitted = st.form_submit_button("➕ Adaugă Gardă", type="primary")
        
        if submitted and selected_doc_id:
            # Verifică dacă există deja
            existing = schedule_df[
                (pd.to_datetime(schedule_df[COL_DATE]).dt.date == shift_date) &
                (schedule_df[COL_SHIFT] == shift_type)
            ] if not schedule_df.empty else pd.DataFrame()
            
            if not existing.empty:
                st.error("❌ Există deja o gardă de acest tip în această zi!")
            else:
                # Adaugă garda
                new_shift = pd.DataFrame([{
                    COL_DATE: shift_date.strftime('%Y-%m-%d'),
                    COL_SHIFT: shift_type,
                    COL_DOC_ID: selected_doc_id
                }])
                
                if schedule_df.empty:
                    schedule_df = new_shift
                else:
                    schedule_df = pd.concat([schedule_df, new_shift], ignore_index=True)
                
                # Salvează și reîncarcă
                sheet_id = st.session_state.get('sheet_id')
                if sheet_id:
                    save_data(SHEET_SCHEDULE, schedule_df, sheet_id)
                    st.success("✅ Gardă adăugată cu succes!")
                    st.rerun()

def get_available_doctors(doctors_df, unavail_df, check_date):
    """Returnează medicii disponibili pentru o anumită dată."""
    if doctors_df.empty:
        return pd.DataFrame()
    
    available = doctors_df.copy()
    
    # Elimină medicii indisponibili
    if not unavail_df.empty:
        unavail_on_date = unavail_df[
            pd.to_datetime(unavail_df['date']).dt.date == check_date
        ]
        
        if not unavail_on_date.empty:
            unavail_ids = unavail_on_date['doctor_id'].unique()
            available = available[~available[COL_ID].isin(unavail_ids)]
    
    return available

# ──────────────────────────────────────────────────────────
# Generare automată simplă
# ──────────────────────────────────────────────────────────
def generate_schedule_simple(doctors_df, start_date, end_date, shift_types, unavail_df):
    """Generează program simplu folosind Round-Robin."""
    if doctors_df.empty:
        st.error("❌ Nu există personal înregistrat!")
        return pd.DataFrame()
    
    # Pregătește lista de medici și contoare
    doctor_ids = doctors_df[COL_ID].tolist()
    shifts_count = defaultdict(int)
    max_shifts = dict(zip(doctors_df[COL_ID], doctors_df[COL_MAX]))
    
    # Generare program
    schedule_rows = []
    current_date = start_date
    doctor_index = 0
    
    while current_date <= end_date:
        for shift_type in shift_types:
            # Găsește medic disponibil
            attempts = 0
            assigned = False
            
            while attempts < len(doctor_ids) and not assigned:
                doc_id = doctor_ids[doctor_index % len(doctor_ids)]
                
                # Verifică disponibilitate
                is_available = True
                if not unavail_df.empty:
                    unavail_check = unavail_df[
                        (unavail_df['doctor_id'] == doc_id) &
                        (pd.to_datetime(unavail_df['date']).dt.date == current_date)
                    ]
                    is_available = unavail_check.empty
                
                # Verifică limita lunară
                month_key = f"{current_date.year}-{current_date.month}"
                under_limit = shifts_count[f"{doc_id}_{month_key}"] < max_shifts.get(doc_id, 8)
                
                if is_available and under_limit:
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
                st.warning(f"⚠️ Nu s-a găsit medic pentru {current_date.strftime('%d.%m.%Y')} - {shift_type}")
        
        current_date += timedelta(days=1)
    
    return pd.DataFrame(schedule_rows)

# ──────────────────────────────────────────────────────────
# Aplicația principală
# ──────────────────────────────────────────────────────────
def main():
    # Inițializare session state
    init_session_state()
    
    # Configurare spital
    hospitals = get_hospital_config()
    
    # Selector spital (în sidebar dacă sunt mai multe)
    if len(hospitals) > 1:
        with st.sidebar:
            st.markdown("### 🏥 Selectează Spitalul")
            selected_hospital = st.selectbox(
                "Spital:",
                options=list(hospitals.keys()),
                format_func=lambda x: hospitals[x]["name"]
            )
    else:
        selected_hospital = list(hospitals.keys())[0]
    
    sheet_id = hospitals[selected_hospital]["sheet_id"]
    st.session_state['sheet_id'] = sheet_id
    hospital_name = hospitals[selected_hospital]["name"]
    
    # Header principal
    st.title(f"🏥 {hospital_name} - Planificare Gărzi")
    
    # Încarcă datele cu caching
    doctors_df = load_data(SHEET_DOCTORS, sheet_id)
    schedule_df = load_data(SHEET_SCHEDULE, sheet_id)
    unavail_df = load_data(SHEET_UNAVAILABLE, sheet_id)
    
    # Curățare date medici
    if not doctors_df.empty:
        doctors_df[COL_ID] = pd.to_numeric(doctors_df[COL_ID], errors='coerce').fillna(0).astype(int)
        doctors_df = doctors_df[doctors_df[COL_ID] > 0]
        doctors_df[COL_MAX] = pd.to_numeric(doctors_df[COL_MAX], errors='coerce').fillna(8).astype(int)
    
    # Selector utilizator
    create_user_selector(doctors_df)
    
    # Tabs principale
    if st.session_state.user_role == 'manager':
        tabs = st.tabs(["📅 Calendar", "📊 Gantt", "📋 Tabel", "🔧 Alocare", "👥 Personal", "⚙️ Generare"])
    elif st.session_state.user_role == 'doctor':
        tabs = st.tabs(["📅 Calendar", "📊 Gantt", "📋 Tabel", "🚫 Indisponibilități"])
    else:
        tabs = st.tabs(["📅 Calendar", "📊 Gantt", "📋 Tabel"])
    
    # Tab Calendar
    with tabs[0]:
        st.header("📅 Vizualizare Calendar")
        show_calendar_view(
            schedule_df, 
            doctors_df,
            st.session_state.selected_month,
            st.session_state.selected_year
        )
    
    # Tab Gantt
    with tabs[1]:
        st.header("📊 Diagramă Gantt")
        
        # Selector perioadă
        col1, col2 = st.columns(2)
        with col1:
            gantt_start = st.date_input("De la:", value=date.today(), key="gantt_start")
        with col2:
            gantt_end = st.date_input("Până la:", value=date.today() + timedelta(days=14), key="gantt_end")
        
        show_gantt_view(schedule_df, doctors_df, gantt_start, gantt_end)
    
    # Tab Tabel
    with tabs[2]:
        st.header("📋 Vizualizare Tabel")
        
        # Selector perioadă
        col1, col2 = st.columns(2)
        with col1:
            table_start = st.date_input("De la:", value=date.today(), key="table_start")
        with col2:
            table_end = st.date_input("Până la:", value=date.today() + timedelta(days=30), key="table_end")
        
        show_table_view(schedule_df, doctors_df, table_start, table_end)
    
    # Funcționalități Manager
    if st.session_state.user_role == 'manager':
        # Tab Alocare
        with tabs[3]:
            st.header("🔧 Alocare Manuală")
            show_manager_allocation(schedule_df, doctors_df, unavail_df)
            
            # Ștergere gărzi
            if not schedule_df.empty:
                st.divider()
                st.subheader("🗑️ Ștergere Gărzi")
                
                # Pregătește date pentru afișare
                delete_df = schedule_df.copy()
                id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
                delete_df['Medic'] = delete_df[COL_DOC_ID].map(id_to_name)
                delete_df['Data'] = pd.to_datetime(delete_df[COL_DATE]).dt.strftime('%d.%m.%Y')
                delete_df = delete_df.sort_values(COL_DATE, ascending=False).head(20)
                
                for idx, row in delete_df.iterrows():
                    col1, col2, col3, col4 = st.columns([2, 3, 3, 1])
                    with col1:
                        st.write(row['Data'])
                    with col2:
                        st.write(row[COL_SHIFT])
                    with col3:
                        st.write(row['Medic'])
                    with col4:
                        if st.button("🗑️", key=f"del_{idx}"):
                            schedule_df = schedule_df.drop(idx)
                            save_data(SHEET_SCHEDULE, schedule_df, sheet_id)
                            st.rerun()
        
        # Tab Personal
        with tabs[4]:
            st.header("👥 Gestionare Personal")
            
            if doctors_df.empty:
                doctors_df = pd.DataFrame(columns=[COL_ID, COL_NAME, COL_SPEC, COL_MAX, COL_PHONE, COL_EMAIL])
            
            edited = st.data_editor(
                doctors_df,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                column_config={
                    COL_ID: st.column_config.NumberColumn("ID", min_value=1, required=True),
                    COL_NAME: st.column_config.TextColumn("Nume", required=True),
                    COL_SPEC: st.column_config.SelectboxColumn("Specialitate", options=SPECIALTIES, required=True),
                    COL_MAX: st.column_config.NumberColumn("Max Gărzi/Lună", min_value=1, max_value=15, default=8),
                    COL_PHONE: st.column_config.TextColumn("Telefon"),
                    COL_EMAIL: st.column_config.TextColumn("Email")
                }
            )
            
            if st.button("💾 Salvează Modificări", type="primary"):
                if edited[COL_ID].duplicated().any():
                    st.error("❌ Există ID-uri duplicate!")
                else:
                    save_data(SHEET_DOCTORS, edited, sheet_id)
                    st.success("✅ Lista personal salvată!")
                    st.rerun()
        
        # Tab Generare
        with tabs[5]:
            st.header("⚙️ Generare Automată")
            
            col1, col2 = st.columns(2)
            with col1:
                gen_start = st.date_input("De la:", value=date.today())
            with col2:
                gen_end = st.date_input("Până la:", value=date.today() + timedelta(days=30))
            
            # Selectare tipuri de ture
            st.subheader("Tipuri de ture")
            selected_shifts = st.multiselect(
                "Selectează turele necesare:",
                options=list(SHIFT_CONFIGS.keys()),
                default=["Gardă 24h"]
            )
            
            if st.button("🚀 Generează Program", type="primary", use_container_width=True):
                if gen_start <= gen_end and selected_shifts:
                    with st.spinner("Generez programul..."):
                        new_schedule = generate_schedule_simple(
                            doctors_df, gen_start, gen_end, selected_shifts, unavail_df
                        )
                        
                        if not new_schedule.empty:
                            save_data(SHEET_SCHEDULE, new_schedule, sheet_id)
                            st.success("✅ Program generat cu succes!")
                            st.balloons()
                            st.rerun()
                else:
                    st.error("❌ Verifică datele selectate!")
    
    # Funcționalități Medic
    if st.session_state.user_role == 'doctor' and st.session_state.selected_user:
        with tabs[3]:
            st.header("🚫 Gestionare Indisponibilități")
            
            doc_id = st.session_state.selected_user['id']
            doc_name = st.session_state.selected_user['name']
            
            st.subheader(f"Indisponibilități pentru {doc_name}")
            
            # Calendar pentru selectare
            selected_dates = st.date_input(
                "Selectează zilele când NU poți lua gărzi:",
                value=[],
                min_value=date.today(),
                max_value=date.today() + timedelta(days=90),
                key="unavail_dates"
            )
            
            if st.button("💾 Salvează Indisponibilități", type="primary"):
                # Șterge indisponibilitățile vechi ale medicului
                if not unavail_df.empty:
                    unavail_df = unavail_df[unavail_df['doctor_id'] != doc_id]
                
                # Adaugă cele noi
                new_unavail_rows = []
                for sel_date in selected_dates:
                    new_unavail_rows.append({
                        'doctor_id': doc_id,
                        'date': sel_date.strftime('%Y-%m-%d'),
                        'reason': 'Indisponibil'
                    })
                
                if new_unavail_rows:
                    new_unavail = pd.DataFrame(new_unavail_rows)
                    if unavail_df.empty:
                        unavail_df = new_unavail
                    else:
                        unavail_df = pd.concat([unavail_df, new_unavail], ignore_index=True)
                
                save_data(SHEET_UNAVAILABLE, unavail_df, sheet_id)
                st.success("✅ Indisponibilități salvate!")
                st.rerun()
            
            # Afișare indisponibilități curente
            if not unavail_df.empty:
                my_unavail = unavail_df[unavail_df['doctor_id'] == doc_id]
                if not my_unavail.empty:
                    st.divider()
                    st.write("**Zile marcate ca indisponibile:**")
                    dates = pd.to_datetime(my_unavail['date']).dt.strftime('%d.%m.%Y')
                    st.write(", ".join(dates.tolist()))
    
    # Export funcționalitate (pentru toți utilizatorii)
    with st.sidebar:
        st.divider()
        st.subheader("📤 Export")
        
        if not schedule_df.empty:
            # Generare text pentru export
            export_text = f"PROGRAM GĂRZI - {hospital_name}\n"
            export_text += "=" * 50 + "\n\n"
            export_text += f"Generat: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            
            # Sortare și formatare
            id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
            schedule_sorted = schedule_df.sort_values(COL_DATE)
            
            current_month = None
            for _, row in schedule_sorted.iterrows():
                date_obj = pd.to_datetime(row[COL_DATE])
                
                # Header lună nouă
                if date_obj.month != current_month:
                    current_month = date_obj.month
                    export_text += f"\n--- {calendar.month_name[current_month]} {date_obj.year} ---\n\n"
                
                weekday = WEEKDAYS_RO[date_obj.weekday()]
                doc_name = id_to_name.get(row[COL_DOC_ID], "Necunoscut")
                
                export_text += f"{weekday}, {date_obj.strftime('%d.%m.%Y')}: {row[COL_SHIFT]} - {doc_name}\n"
            
            # Buton download
            st.download_button(
                "📥 Descarcă Program (.txt)",
                export_text,
                f"program_{date.today()}.txt",
                "text/plain",
                use_container_width=True
            )
        else:
            st.info("Nu există program de exportat")

if __name__ == "__main__":
    main()
