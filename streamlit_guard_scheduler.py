#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistem de Planificare Gărzi Medicale - Versiune Manager
Versiune: 7.0 - Cu rol Manager și vizualizare îmbunătățită
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict
import io
import calendar
import locale

# Setare limba română pentru zile
try:
    locale.setlocale(locale.LC_TIME, 'ro_RO.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'ro_RO')
    except:
        pass  # Continuă cu setările implicite

# ──────────────────────────────────────────────────────────
# CONFIGURARE ȘI CONSTANTE
# ──────────────────────────────────────────────────────────
# Nume foi în Google Sheets
SHEET_DOCTORS = "Doctors"
SHEET_SCHEDULE = "Schedule"
SHEET_UNAVAILABLE = "Unavailable"
SHEET_TEMPLATES = "Templates"

# Coloane pentru tabele
COL_ID = "id"
COL_NAME = "name"
COL_SPEC = "speciality"
COL_MAX = "max_shifts_per_month"
COL_PHONE = "phone"
COL_EMAIL = "email"
COL_DATE = "date"
COL_SHIFT = "shift_name"
COL_DOC_ID = "doctor_id"
COL_MANUAL = "is_manual"  # Pentru a marca gărzi alocate manual

# Coloane indisponibilități
COL_UNAV_DOC = "doctor_id"
COL_UNAV_DATE = "date"
COL_UNAV_REASON = "reason"

# Coloane șabloane
COL_TEMPLATE_NAME = "template_name"
COL_TEMPLATE_DATA = "template_data"

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

# Tipuri de ture
SHIFT_OPTIONS = ["Gardă 24h", "Gardă Zi (08-20)", "Gardă Noapte (20-08)"]

# Zile săptămână în română
WEEKDAYS_RO = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']

# Parolă manager (în producție ar trebui hash-uită și stocată sigur)
MANAGER_PASSWORD = "admin123"  # Schimbați în producție!

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

def select_hospital():
    """Permite selectarea spitalului și returnează sheet_id."""
    hospitals = get_hospital_config()
    keys = list(hospitals.keys())
    
    if len(keys) == 1:
        st.session_state["selected_hospital"] = keys[0]
        return hospitals[keys[0]]["sheet_id"]
    
    with st.sidebar:
        st.markdown("### 🏥 Selectează Spitalul")
        selected = st.selectbox(
            "Spital:",
            options=keys,
            format_func=lambda x: hospitals[x]["name"]
        )
    
    st.session_state["selected_hospital"] = selected
    return hospitals[selected]["sheet_id"]

# ──────────────────────────────────────────────────────────
# Funcții Google Sheets
# ──────────────────────────────────────────────────────────
@st.cache_resource
def get_gsheet_client():
    """Creează clientul Google Sheets."""
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Eroare conectare: {str(e)}")
        st.stop()

def load_data(sheet_name):
    """Încarcă date din foaia specificată."""
    if "sheet_id" not in st.session_state:
        return pd.DataFrame()
    
    try:
        client = get_gsheet_client()
        sh = client.open_by_key(st.session_state["sheet_id"])
        
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

def save_data(sheet_name, df):
    """Salvează date în foaia specificată."""
    if "sheet_id" not in st.session_state or df is None:
        return
    
    try:
        client = get_gsheet_client()
        sh = client.open_by_key(st.session_state["sheet_id"])
        
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
            
    except Exception as e:
        st.error(f"❌ Eroare salvare: {str(e)}")

# ──────────────────────────────────────────────────────────
# Funcții pentru manager
# ──────────────────────────────────────────────────────────
def check_manager_auth():
    """Verifică dacă utilizatorul este autentificat ca manager."""
    if 'is_manager' not in st.session_state:
        st.session_state['is_manager'] = False
    return st.session_state['is_manager']

def manager_login():
    """Afișează formularul de login pentru manager."""
    with st.sidebar.expander("🔐 Acces Manager", expanded=not check_manager_auth()):
        if not check_manager_auth():
            password = st.text_input("Parolă:", type="password", key="manager_pass")
            if st.button("Autentificare"):
                if password == MANAGER_PASSWORD:
                    st.session_state['is_manager'] = True
                    st.success("✅ Autentificare reușită!")
                    st.rerun()
                else:
                    st.error("❌ Parolă incorectă!")
        else:
            st.success("✅ Conectat ca Manager")
            if st.button("🚪 Deconectare"):
                st.session_state['is_manager'] = False
                st.rerun()

# ──────────────────────────────────────────────────────────
# Funcții pentru indisponibilități
# ──────────────────────────────────────────────────────────
def get_unavailable_dates(doctor_id, unavail_df):
    """Returnează setul de date când medicul nu e disponibil."""
    if unavail_df.empty:
        return set()
    
    doctor_unavail = unavail_df[unavail_df[COL_UNAV_DOC] == doctor_id]
    return set(pd.to_datetime(doctor_unavail[COL_UNAV_DATE]).dt.date)

def show_availability_calendar(doctor_id, doctor_name, unavail_df):
    """Afișează calendar pentru selectarea indisponibilităților."""
    st.subheader(f"Calendar indisponibilități - {doctor_name}")
    
    # Obține datele curente de indisponibilitate
    unavailable_dates = get_unavailable_dates(doctor_id, unavail_df)
    
    # Afișează luna curentă și următoarea
    today = date.today()
    
    col1, col2 = st.columns(2)
    
    # Luna curentă
    with col1:
        st.write(f"**{today.strftime('%B %Y')}**")
        cal = calendar.monthcalendar(today.year, today.month)
        
        for week in cal:
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day > 0:
                    day_date = date(today.year, today.month, day)
                    is_weekend = day_date.weekday() >= 5
                    is_unavailable = day_date in unavailable_dates
                    
                    with cols[i]:
                        # Colorare diferită pentru weekend
                        if is_weekend:
                            label = f"**{day}**"
                        else:
                            label = str(day)
                        
                        # Checkbox pentru indisponibilitate
                        key = f"unavail_{doctor_id}_{day_date}"
                        if st.checkbox(label, value=is_unavailable, key=key):
                            if day_date not in unavailable_dates:
                                # Adaugă indisponibilitate
                                new_unavail = pd.DataFrame([{
                                    COL_UNAV_DOC: doctor_id,
                                    COL_UNAV_DATE: day_date.isoformat(),
                                    COL_UNAV_REASON: "Indisponibil"
                                }])
                                unavail_df = pd.concat([unavail_df, new_unavail], ignore_index=True)
                        else:
                            if day_date in unavailable_dates:
                                # Șterge indisponibilitate
                                unavail_df = unavail_df[
                                    ~((unavail_df[COL_UNAV_DOC] == doctor_id) & 
                                      (pd.to_datetime(unavail_df[COL_UNAV_DATE]).dt.date == day_date))
                                ]
    
    # Luna următoare
    next_month = today.replace(day=28) + timedelta(days=4)
    next_month = next_month.replace(day=1)
    
    with col2:
        st.write(f"**{next_month.strftime('%B %Y')}**")
        cal = calendar.monthcalendar(next_month.year, next_month.month)
        
        for week in cal:
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day > 0:
                    day_date = date(next_month.year, next_month.month, day)
                    is_weekend = day_date.weekday() >= 5
                    is_unavailable = day_date in unavailable_dates
                    
                    with cols[i]:
                        if is_weekend:
                            label = f"**{day}**"
                        else:
                            label = str(day)
                        
                        key = f"unavail_{doctor_id}_{day_date}_next"
                        if st.checkbox(label, value=is_unavailable, key=key):
                            if day_date not in unavailable_dates:
                                new_unavail = pd.DataFrame([{
                                    COL_UNAV_DOC: doctor_id,
                                    COL_UNAV_DATE: day_date.isoformat(),
                                    COL_UNAV_REASON: "Indisponibil"
                                }])
                                unavail_df = pd.concat([unavail_df, new_unavail], ignore_index=True)
                        else:
                            if day_date in unavailable_dates:
                                unavail_df = unavail_df[
                                    ~((unavail_df[COL_UNAV_DOC] == doctor_id) & 
                                      (pd.to_datetime(unavail_df[COL_UNAV_DATE]).dt.date == day_date))
                                ]
    
    return unavail_df

# ──────────────────────────────────────────────────────────
# Algoritm de generare automată cu respectarea indisponibilităților
# ──────────────────────────────────────────────────────────
def generate_schedule_with_constraints(doctors_df, start_date, end_date, shift_type, unavail_df, speciality_filter=None):
    """Generează program respectând indisponibilitățile."""
    if doctors_df.empty:
        st.error("❌ Nu există personal înregistrat!")
        return pd.DataFrame()
    
    # Filtrare pe specialitate
    if speciality_filter and speciality_filter != "Toate":
        available_doctors = doctors_df[doctors_df[COL_SPEC] == speciality_filter].copy()
        if available_doctors.empty:
            st.error(f"❌ Nu există personal cu specialitatea {speciality_filter}!")
            return pd.DataFrame()
    else:
        available_doctors = doctors_df.copy()
    
    doctor_ids = available_doctors[COL_ID].tolist()
    if not doctor_ids:
        return pd.DataFrame()
    
    # Pregătește seturile de indisponibilități pentru fiecare medic
    unavail_sets = {}
    for doc_id in doctor_ids:
        unavail_sets[doc_id] = get_unavailable_dates(doc_id, unavail_df)
    
    # Contoare și limite
    shifts_count = defaultdict(int)
    max_shifts = dict(zip(available_doctors[COL_ID], available_doctors[COL_MAX]))
    
    # Tipuri de ture
    if shift_type == 1:
        shifts = ["Gardă 24h"]
    else:
        shifts = ["Gardă Zi (08-20)", "Gardă Noapte (20-08)"]
    
    # Generare program
    schedule_rows = []
    current_date = start_date
    doctor_index = 0
    
    while current_date <= end_date:
        for shift_name in shifts:
            # Găsește medic disponibil
            attempts = 0
            assigned = False
            
            while attempts < len(doctor_ids) and not assigned:
                doc_id = doctor_ids[doctor_index % len(doctor_ids)]
                
                # Verifică disponibilitate și limite
                month_key = f"{current_date.year}-{current_date.month}"
                is_available = current_date not in unavail_sets[doc_id]
                under_limit = shifts_count[f"{doc_id}_{month_key}"] < max_shifts.get(doc_id, 8)
                
                if is_available and under_limit:
                    schedule_rows.append({
                        COL_DATE: current_date.strftime('%Y-%m-%d'),
                        COL_SHIFT: shift_name,
                        COL_DOC_ID: doc_id,
                        COL_MANUAL: False
                    })
                    shifts_count[f"{doc_id}_{month_key}"] += 1
                    assigned = True
                
                doctor_index += 1
                attempts += 1
            
            if not assigned:
                st.warning(f"⚠️ Nu s-a găsit medic disponibil pentru {current_date.strftime('%d.%m.%Y')} - {shift_name}")
        
        current_date += timedelta(days=1)
    
    return pd.DataFrame(schedule_rows)

# ──────────────────────────────────────────────────────────
# Vizualizare tip Gantt îmbunătățită
# ──────────────────────────────────────────────────────────
def show_gantt_view(schedule_df, doctors_df, start_date, end_date):
    """Afișează programul în format Gantt similar cu imaginea."""
    if schedule_df.empty:
        st.info("📅 Nu există program generat.")
        return
    
    # Mapare ID -> Nume
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    
    # Pregătește datele
    schedule_df = schedule_df.copy()
    schedule_df['date_obj'] = pd.to_datetime(schedule_df[COL_DATE])
    
    # Filtrează pentru perioada selectată
    mask = (schedule_df['date_obj'].dt.date >= start_date) & (schedule_df['date_obj'].dt.date <= end_date)
    filtered_schedule = schedule_df[mask]
    
    if filtered_schedule.empty:
        st.info("Nu există gărzi în perioada selectată.")
        return
    
    # Obține lista de medici din program
    scheduled_doctors = filtered_schedule[COL_DOC_ID].unique()
    doctor_names = [id_to_name.get(doc_id, f"ID {doc_id}") for doc_id in scheduled_doctors]
    
    # Creează header cu datele
    dates = pd.date_range(start_date, end_date)
    
    # CSS pentru stilizare
    st.markdown("""
    <style>
    .gantt-container {
        background: white;
        border: 1px solid #ddd;
        border-radius: 5px;
        overflow-x: auto;
        margin: 10px 0;
    }
    .gantt-header {
        display: flex;
        background: #f8f9fa;
        border-bottom: 2px solid #333;
        position: sticky;
        top: 0;
        z-index: 10;
    }
    .gantt-row {
        display: flex;
        border-bottom: 1px solid #eee;
        min-height: 40px;
    }
    .gantt-cell {
        flex: 1;
        min-width: 60px;
        padding: 5px;
        text-align: center;
        border-right: 1px solid #eee;
        position: relative;
    }
    .gantt-name {
        min-width: 150px;
        font-weight: bold;
        background: #f8f9fa;
        position: sticky;
        left: 0;
        z-index: 5;
    }
    .gantt-weekend {
        background: #fff3cd !important;
    }
    .gantt-shift {
        background: #007bff;
        color: white;
        border-radius: 3px;
        padding: 2px 5px;
        margin: 2px;
        font-size: 12px;
        white-space: nowrap;
    }
    .gantt-shift-24h {
        background: #dc3545;
    }
    .gantt-shift-day {
        background: #28a745;
    }
    .gantt-shift-night {
        background: #17a2b8;
    }
    .gantt-shift-manual {
        border: 2px solid #ffc107;
    }
    .gantt-date-header {
        font-weight: bold;
        font-size: 14px;
    }
    .gantt-weekday {
        font-size: 11px;
        color: #666;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Construiește HTML pentru Gantt
    html = '<div class="gantt-container">'
    
    # Header cu date
    html += '<div class="gantt-header">'
    html += '<div class="gantt-cell gantt-name">Personal</div>'
    for d in dates:
        weekday = WEEKDAYS_RO[d.weekday()]
        is_weekend = d.weekday() >= 5
        weekend_class = "gantt-weekend" if is_weekend else ""
        html += f'''
        <div class="gantt-cell {weekend_class}">
            <div class="gantt-date-header">{d.day}</div>
            <div class="gantt-weekday">{weekday[:3]}</div>
        </div>
        '''
    html += '</div>'
    
    # Rânduri pentru fiecare medic
    for doc_id, doc_name in zip(scheduled_doctors, doctor_names):
        html += '<div class="gantt-row">'
        html += f'<div class="gantt-cell gantt-name">{doc_name}</div>'
        
        # Pentru fiecare dată
        for d in dates:
            is_weekend = d.weekday() >= 5
            weekend_class = "gantt-weekend" if is_weekend else ""
            
            # Găsește gărzi pentru acest medic în această zi
            day_shifts = filtered_schedule[
                (filtered_schedule[COL_DOC_ID] == doc_id) & 
                (filtered_schedule['date_obj'].dt.date == d.date())
            ]
            
            html += f'<div class="gantt-cell {weekend_class}">'
            
            for _, shift in day_shifts.iterrows():
                shift_type = shift[COL_SHIFT]
                is_manual = shift.get(COL_MANUAL, False)
                
                # Determină clasa pentru culoare
                if "24h" in shift_type:
                    shift_class = "gantt-shift-24h"
                elif "Zi" in shift_type:
                    shift_class = "gantt-shift-day"
                else:
                    shift_class = "gantt-shift-night"
                
                manual_class = "gantt-shift-manual" if is_manual else ""
                
                # Afișează ora pentru ture de 12h
                if "08-20" in shift_type:
                    display_text = "08-20"
                elif "20-08" in shift_type:
                    display_text = "20-08"
                else:
                    display_text = "24h"
                
                html += f'<div class="gantt-shift {shift_class} {manual_class}">{display_text}</div>'
            
            html += '</div>'
        
        html += '</div>'
    
    html += '</div>'
    
    # Legendă
    html += '''
    <div style="margin-top: 20px; padding: 10px; background: #f8f9fa; border-radius: 5px;">
        <strong>Legendă:</strong>
        <span class="gantt-shift gantt-shift-24h" style="margin: 0 10px;">Gardă 24h</span>
        <span class="gantt-shift gantt-shift-day" style="margin: 0 10px;">Gardă Zi</span>
        <span class="gantt-shift gantt-shift-night" style="margin: 0 10px;">Gardă Noapte</span>
        <span class="gantt-shift gantt-shift-manual" style="margin: 0 10px; background: white; color: black;">Alocare manuală</span>
        <span style="background: #fff3cd; padding: 2px 8px; margin: 0 10px; border: 1px solid #ddd;">Weekend</span>
    </div>
    '''
    
    st.markdown(html, unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────
# Funcții Manager pentru alocare manuală
# ──────────────────────────────────────────────────────────
def show_manual_allocation(schedule_df, doctors_df, unavail_df):
    """Interfață pentru alocare manuală de gărzi."""
    st.subheader("🔧 Alocare Manuală Gărzi")
    
    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
    
    with col1:
        selected_date = st.date_input("Data:", value=date.today())
    
    with col2:
        shift_type = st.selectbox("Tip gardă:", SHIFT_OPTIONS)
    
    with col3:
        if not doctors_df.empty:
            doctor_options = dict(zip(
                doctors_df[COL_NAME] + " (" + doctors_df[COL_SPEC] + ")",
                doctors_df[COL_ID]
            ))
            selected_doc_display = st.selectbox("Medic:", list(doctor_options.keys()))
            selected_doc_id = doctor_options[selected_doc_display]
        else:
            st.warning("Nu există medici înregistrați")
            selected_doc_id = None
    
    with col4:
        if st.button("➕ Adaugă", type="primary", disabled=selected_doc_id is None):
            # Verifică indisponibilitate
            unavail_dates = get_unavailable_dates(selected_doc_id, unavail_df)
            
            if selected_date in unavail_dates:
                st.error("❌ Medicul nu este disponibil în această zi!")
            else:
                # Adaugă garda manuală
                new_shift = pd.DataFrame([{
                    COL_DATE: selected_date.strftime('%Y-%m-%d'),
                    COL_SHIFT: shift_type,
                    COL_DOC_ID: selected_doc_id,
                    COL_MANUAL: True
                }])
                
                if schedule_df.empty:
                    schedule_df = new_shift
                else:
                    schedule_df = pd.concat([schedule_df, new_shift], ignore_index=True)
                
                save_data(SHEET_SCHEDULE, schedule_df)
                st.success("✅ Gardă adăugată manual!")
                st.rerun()

def save_template(schedule_df, template_name):
    """Salvează programul curent ca șablon."""
    if schedule_df.empty:
        st.error("Nu există program de salvat!")
        return
    
    # Salvează doar structura (fără date specifice)
    template_data = schedule_df.to_json()
    
    templates_df = load_data(SHEET_TEMPLATES)
    
    new_template = pd.DataFrame([{
        COL_TEMPLATE_NAME: template_name,
        COL_TEMPLATE_DATA: template_data,
        'created_at': datetime.now().isoformat()
    }])
    
    if templates_df.empty:
        templates_df = new_template
    else:
        # Înlocuiește dacă există
        templates_df = templates_df[templates_df[COL_TEMPLATE_NAME] != template_name]
        templates_df = pd.concat([templates_df, new_template], ignore_index=True)
    
    save_data(SHEET_TEMPLATES, templates_df)
    st.success(f"✅ Șablon '{template_name}' salvat!")

def load_template(template_name):
    """Încarcă un șablon salvat."""
    templates_df = load_data(SHEET_TEMPLATES)
    
    if templates_df.empty:
        st.error("Nu există șabloane salvate!")
        return None
    
    template = templates_df[templates_df[COL_TEMPLATE_NAME] == template_name]
    
    if template.empty:
        st.error(f"Șablonul '{template_name}' nu există!")
        return None
    
    try:
        return pd.read_json(template.iloc[0][COL_TEMPLATE_DATA])
    except:
        st.error("Eroare la încărcarea șablonului!")
        return None

# ──────────────────────────────────────────────────────────
# Aplicația principală
# ──────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="🩺 Planificare Gărzi - Manager",
        page_icon="🏥",
        layout="wide"
    )
    
    # Selectare spital
    sheet_id = select_hospital()
    st.session_state["sheet_id"] = sheet_id
    
    # Login manager
    manager_login()
    is_manager = check_manager_auth()
    
    # Header
    hospitals = get_hospital_config()
    hospital_name = hospitals.get(
        st.session_state.get('selected_hospital', 'default'), 
        {}
    ).get('name', 'Spital')
    
    st.title(f"🏥 Planificare Gărzi - {hospital_name}")
    if is_manager:
        st.caption("👨‍💼 Mod Manager Activ")
    
    # Încarcă datele
    doctors_df = load_data(SHEET_DOCTORS)
    schedule_df = load_data(SHEET_SCHEDULE)
    unavail_df = load_data(SHEET_UNAVAILABLE)
    
    # Curățare date
    if not doctors_df.empty:
        for col in [COL_ID, COL_NAME, COL_SPEC, COL_MAX]:
            if col not in doctors_df.columns:
                doctors_df[col] = ""
        
        doctors_df[COL_ID] = pd.to_numeric(doctors_df[COL_ID], errors='coerce').fillna(0).astype(int)
        doctors_df = doctors_df[doctors_df[COL_ID] > 0]
        doctors_df[COL_MAX] = pd.to_numeric(doctors_df[COL_MAX], errors='coerce').fillna(8).astype(int)
    
    # Sidebar pentru generare
    with st.sidebar:
        st.header("⚙️ Generare Program")
        
        if doctors_df.empty:
            st.error("❌ Nu există personal!")
        else:
            st.success(f"✅ {len(doctors_df)} medici")
        
        # Perioada
        st.subheader("📅 Perioada")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("De la:", value=date.today())
        with col2:
            end_date = st.date_input("Până la:", value=date.today() + timedelta(days=30))
        
        # Tip ture
        st.subheader("🕐 Tip Ture")
        shift_type = st.radio(
            "Selectează:",
            options=[1, 2],
            format_func=lambda x: "O tură de 24h" if x == 1 else "Două ture de 12h",
            horizontal=True
        )
        
        # Filtru specialitate
        st.subheader("👨‍⚕️ Filtru Specialitate")
        speciality_options = ["Toate"] + SPECIALTIES
        selected_speciality = st.selectbox(
            "Generează pentru:",
            options=speciality_options
        )
        
        # Buton generare
        if st.button("🚀 Generează Automat", type="primary", use_container_width=True):
            if start_date <= end_date:
                with st.spinner("Generez programul..."):
                    new_schedule = generate_schedule_with_constraints(
                        doctors_df, 
                        start_date, 
                        end_date, 
                        shift_type,
                        unavail_df,
                        selected_speciality if selected_speciality != "Toate" else None
                    )
                    
                    if not new_schedule.empty:
                        # Păstrează gărzile manuale existente
                        if not schedule_df.empty and COL_MANUAL in schedule_df.columns:
                            manual_shifts = schedule_df[schedule_df[COL_MANUAL] == True]
                            new_schedule = pd.concat([manual_shifts, new_schedule], ignore_index=True)
                        
                        save_data(SHEET_SCHEDULE, new_schedule)
                        st.success("✅ Program generat!")
                        st.rerun()
            else:
                st.error("❌ Data de început trebuie să fie înainte de cea de sfârșit!")
        
        # Opțiuni Manager
        if is_manager:
            st.divider()
            st.subheader("🔧 Opțiuni Manager")
            
            # Șabloane
            with st.expander("📋 Șabloane"):
                templates_df = load_data(SHEET_TEMPLATES)
                
                if not templates_df.empty:
                    template = st.selectbox(
                        "Încarcă șablon:",
                        ["---"] + templates_df[COL_TEMPLATE_NAME].tolist()
                    )
                    
                    if template != "---" and st.button("📥 Încarcă"):
                        loaded = load_template(template)
                        if loaded is not None:
                            save_data(SHEET_SCHEDULE, loaded)
                            st.success("✅ Șablon încărcat!")
                            st.rerun()
                
                new_template_name = st.text_input("Nume șablon nou:")
                if st.button("💾 Salvează ca șablon") and new_template_name:
                    save_template(schedule_df, new_template_name)
    
    # Tabs principale
    tabs = ["📅 Program", "👨‍⚕️ Personal", "🚫 Indisponibilități", "📊 Statistici"]
    if is_manager:
        tabs.insert(1, "🔧 Alocare Manuală")
    
    tab_list = st.tabs(tabs)
    
    # Tab Program
    with tab_list[0]:
        st.header("📅 Vizualizare Program")
        
        if not schedule_df.empty:
            # Selector perioada vizualizare
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                view_start = st.date_input("Vizualizare de la:", value=date.today(), key="view_start")
            with col2:
                view_end = st.date_input("până la:", value=date.today() + timedelta(days=14), key="view_end")
            
            # Vizualizare Gantt
            show_gantt_view(schedule_df, doctors_df, view_start, view_end)
            
            # Export
            st.divider()
            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader("📤 Export Program")
            with col2:
                # Pregătește export text
                id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
                export_text = "PROGRAM GĂRZI MEDICALE\n"
                export_text += "=" * 50 + "\n\n"
                export_text += f"Generat: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                
                schedule_sorted = schedule_df.sort_values(COL_DATE)
                current_date = None
                
                for _, row in schedule_sorted.iterrows():
                    if row[COL_DATE] != current_date:
                        current_date = row[COL_DATE]
                        date_obj = pd.to_datetime(current_date)
                        weekday = WEEKDAYS_RO[date_obj.weekday()]
                        export_text += f"\n{weekday}, {date_obj.strftime('%d.%m.%Y')}\n"
                        export_text += "-" * 30 + "\n"
                    
                    doc_name = id_to_name.get(row[COL_DOC_ID], "Necunoscut")
                    manual_mark = " (M)" if row.get(COL_MANUAL, False) else ""
                    export_text += f"  {row[COL_SHIFT]}: {doc_name}{manual_mark}\n"
                
                st.download_button(
                    "📥 Descarcă .txt",
                    export_text,
                    f"program_garzi_{date.today()}.txt",
                    "text/plain",
                    use_container_width=True
                )
        else:
            st.info("Nu există program generat.")
    
    # Tab Alocare Manuală (doar pentru Manager)
    if is_manager:
        with tab_list[1]:
            st.header("🔧 Alocare Manuală")
            show_manual_allocation(schedule_df, doctors_df, unavail_df)
            
            # Afișare gărzi manuale existente
            if not schedule_df.empty and COL_MANUAL in schedule_df.columns:
                manual_shifts = schedule_df[schedule_df[COL_MANUAL] == True]
                if not manual_shifts.empty:
                    st.divider()
                    st.subheader("Gărzi alocate manual")
                    
                    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
                    display_manual = manual_shifts.copy()
                    display_manual['Medic'] = display_manual[COL_DOC_ID].map(id_to_name)
                    display_manual['Data'] = pd.to_datetime(display_manual[COL_DATE]).dt.strftime('%d.%m.%Y')
                    
                    for idx, row in display_manual.iterrows():
                        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
                        with col1:
                            st.write(row['Data'])
                        with col2:
                            st.write(row[COL_SHIFT])
                        with col3:
                            st.write(row['Medic'])
                        with col4:
                            if st.button("🗑️", key=f"del_manual_{idx}"):
                                schedule_df = schedule_df.drop(idx)
                                save_data(SHEET_SCHEDULE, schedule_df)
                                st.rerun()
    
    # Tab Personal
    tab_idx = 2 if is_manager else 1
    with tab_list[tab_idx]:
        st.header("👨‍⚕️ Gestionare Personal")
        
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
        
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("💾 Salvează", type="primary", use_container_width=True):
                if edited[COL_ID].duplicated().any():
                    st.error("❌ Există ID-uri duplicate!")
                else:
                    save_data(SHEET_DOCTORS, edited)
                    st.success("✅ Lista salvată!")
                    st.rerun()
    
    # Tab Indisponibilități
    tab_idx = 3 if is_manager else 2
    with tab_list[tab_idx]:
        st.header("🚫 Gestionare Indisponibilități")
        
        if doctors_df.empty:
            st.info("Nu există personal înregistrat.")
        else:
            # Selector medic
            doctor_options = dict(zip(
                doctors_df[COL_NAME] + " - " + doctors_df[COL_SPEC],
                doctors_df[COL_ID]
            ))
            
            selected_doc_display = st.selectbox(
                "Selectează medicul:",
                list(doctor_options.keys())
            )
            selected_doc_id = doctor_options[selected_doc_display]
            selected_doc_name = selected_doc_display.split(" - ")[0]
            
            # Afișează calendar pentru selectare
            updated_unavail = show_availability_calendar(
                selected_doc_id, 
                selected_doc_name,
                unavail_df
            )
            
            # Buton salvare
            if st.button("💾 Salvează indisponibilități", type="primary"):
                save_data(SHEET_UNAVAILABLE, updated_unavail)
                st.success("✅ Indisponibilități salvate!")
                st.rerun()
            
            # Afișare rezumat indisponibilități
            if not unavail_df.empty:
                st.divider()
                st.subheader("Rezumat indisponibilități")
                
                id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
                summary = unavail_df.groupby(COL_UNAV_DOC).size().reset_index(name='Zile indisponibile')
                summary['Medic'] = summary[COL_UNAV_DOC].map(id_to_name)
                
                st.dataframe(
                    summary[['Medic', 'Zile indisponibile']],
                    use_container_width=True,
                    hide_index=True
                )
    
    # Tab Statistici
    tab_idx = 4 if is_manager else 3
    with tab_list[tab_idx]:
        st.header("📊 Statistici")
        
        if not schedule_df.empty:
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Gărzi", len(schedule_df))
                
                if COL_MANUAL in schedule_df.columns:
                    manual_count = schedule_df[COL_MANUAL].sum()
                    st.metric("Alocări Manuale", manual_count)
            
            with col2:
                unique_docs = schedule_df[COL_DOC_ID].nunique()
                st.metric("Medici Activi", unique_docs)
                
                # Weekend shifts
                schedule_df['weekday'] = pd.to_datetime(schedule_df[COL_DATE]).dt.weekday
                weekend_count = len(schedule_df[schedule_df['weekday'] >= 5])
                st.metric("Gărzi Weekend", weekend_count)
            
            with col3:
                try:
                    dates = pd.to_datetime(schedule_df[COL_DATE])
                    date_range = f"{dates.min().strftime('%d.%m')} - {dates.max().strftime('%d.%m')}"
                    st.metric("Perioadă", date_range)
                except:
                    st.metric("Perioadă", "N/A")
            
            # Distribuție
            st.divider()
            st.subheader("Distribuție Gărzi per Medic")
            
            stats = schedule_df[COL_DOC_ID].value_counts()
            id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
            
            stats_df = pd.DataFrame({
                'Medic': [id_to_name.get(doc_id, f"ID {doc_id}") for doc_id in stats.index],
                'Total Gărzi': stats.values
            })
            
            # Adaugă detalii despre tipuri de gărzi
            shift_details = schedule_df.groupby([COL_DOC_ID, COL_SHIFT]).size().unstack(fill_value=0)
            
            for doc_id in stats.index:
                if doc_id in shift_details.index:
                    for shift_type in shift_details.columns:
                        col_name = f"Gărzi {shift_type.split('(')[0].strip()}"
                        idx = stats_df[stats_df['Medic'] == id_to_name.get(doc_id, f"ID {doc_id}")].index[0]
                        stats_df.loc[idx, col_name] = shift_details.loc[doc_id, shift_type]
            
            st.dataframe(stats_df, use_container_width=True, hide_index=True)
            
            # Grafic
            st.bar_chart(stats_df.set_index('Medic')['Total Gărzi'])
        else:
            st.info("Nu există date pentru statistici.")

if __name__ == "__main__":
    main()
