#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistem de Planificare Gărzi cu Rezervări
Versiune: 8.0 - Flux bazat pe rezervări și priorități
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict
import calendar
import random
import json

# ──────────────────────────────────────────────────────────
# CONFIGURARE ȘI CONSTANTE
# ──────────────────────────────────────────────────────────
# Nume foi în Google Sheets
SHEET_DOCTORS = "Doctors"
SHEET_SCHEDULE = "Schedule"
SHEET_RESERVATIONS = "Reservations"
SHEET_PRIORITIES = "Priorities"
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
COL_STATUS = "status"  # Pentru rezervări: pending, approved, rejected

# Coloane rezervări
COL_RES_ID = "reservation_id"
COL_RES_DOC = "doctor_id"
COL_RES_DATE = "date"
COL_RES_SHIFT = "shift_type"
COL_RES_STATUS = "status"
COL_RES_TIMESTAMP = "timestamp"

# Coloane priorități
COL_PRIO_DOC = "doctor_id"
COL_PRIO_MONTH = "month"
COL_PRIO_SCORE = "priority_score"

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

# Tipuri de ture
SHIFT_TYPES = {
    "24h": "Gardă 24h",
    "zi": "Gardă Zi (08-20)",
    "noapte": "Gardă Noapte (20-08)"
}

# Zile săptămână în română
WEEKDAYS_RO = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']

# Parolă manager
MANAGER_PASSWORD = "admin123"

# Culori pentru calendar
COLORS = {
    "24h": "#DC3545",
    "zi": "#28A745",
    "noapte": "#17A2B8",
    "reserved": "#FFC107",
    "unavailable": "#6C757D",
    "weekend": "#FFF3CD"
}

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
    """Permite selectarea spitalului."""
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
# Funcții pentru autentificare
# ──────────────────────────────────────────────────────────
def check_auth():
    """Verifică tipul de utilizator autentificat."""
    return st.session_state.get('user_role', None)

def show_login():
    """Afișează interfața de autentificare."""
    st.title("🏥 Sistem Planificare Gărzi")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("### 🔐 Autentificare")
        
        role = st.radio(
            "Selectează rolul:",
            ["Medic", "Manager"],
            horizontal=True
        )
        
        if role == "Medic":
            doctors_df = load_data(SHEET_DOCTORS)
            if not doctors_df.empty:
                doctor_options = dict(zip(
                    doctors_df[COL_NAME] + " - " + doctors_df[COL_SPEC],
                    doctors_df[COL_ID]
                ))
                
                selected = st.selectbox(
                    "Selectează numele tău:",
                    list(doctor_options.keys())
                )
                
                if st.button("Intră", type="primary", use_container_width=True):
                    st.session_state['user_role'] = 'doctor'
                    st.session_state['doctor_id'] = doctor_options[selected]
                    st.session_state['doctor_name'] = selected.split(" - ")[0]
                    st.rerun()
            else:
                st.error("Nu există medici înregistrați în sistem!")
        
        else:  # Manager
            password = st.text_input("Parolă:", type="password")
            
            if st.button("Autentificare", type="primary", use_container_width=True):
                if password == MANAGER_PASSWORD:
                    st.session_state['user_role'] = 'manager'
                    st.success("✅ Autentificare reușită!")
                    st.rerun()
                else:
                    st.error("❌ Parolă incorectă!")

def logout():
    """Deconectare utilizator."""
    for key in ['user_role', 'doctor_id', 'doctor_name']:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

# ──────────────────────────────────────────────────────────
# Funcții pentru rezervări
# ──────────────────────────────────────────────────────────
def get_doctor_reservations(doctor_id, reservations_df):
    """Obține rezervările unui medic."""
    if reservations_df.empty:
        return pd.DataFrame()
    
    return reservations_df[reservations_df[COL_RES_DOC] == doctor_id]

def get_unavailable_dates(doctor_id, unavail_df):
    """Obține datele când medicul nu e disponibil."""
    if unavail_df.empty:
        return set()
    
    doctor_unavail = unavail_df[unavail_df['doctor_id'] == doctor_id]
    return set(pd.to_datetime(doctor_unavail['date']).dt.date)

def add_reservation(doctor_id, selected_date, shift_type, reservations_df):
    """Adaugă o rezervare nouă."""
    new_reservation = pd.DataFrame([{
        COL_RES_ID: f"RES_{datetime.now().timestamp()}",
        COL_RES_DOC: doctor_id,
        COL_RES_DATE: selected_date.strftime('%Y-%m-%d'),
        COL_RES_SHIFT: shift_type,
        COL_RES_STATUS: 'pending',
        COL_RES_TIMESTAMP: datetime.now().isoformat()
    }])
    
    if reservations_df.empty:
        return new_reservation
    else:
        return pd.concat([reservations_df, new_reservation], ignore_index=True)

def show_reservation_calendar(doctor_id, doctor_name, reservations_df, unavail_df, schedule_df):
    """Afișează calendar pentru rezervări."""
    st.subheader(f"📅 Calendar Rezervări - {doctor_name}")
    
    # Obține rezervările și indisponibilitățile
    my_reservations = get_doctor_reservations(doctor_id, reservations_df)
    unavailable_dates = get_unavailable_dates(doctor_id, unavail_df)
    
    # Selectoare pentru dată și tip gardă
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        selected_date = st.date_input(
            "Selectează data:",
            min_value=date.today(),
            max_value=date.today() + timedelta(days=60)
        )
    
    with col2:
        shift_type = st.selectbox(
            "Tip gardă:",
            options=list(SHIFT_TYPES.keys()),
            format_func=lambda x: SHIFT_TYPES[x]
        )
    
    with col3:
        # Verificări pentru adăugare
        can_add = True
        reason = ""
        
        if selected_date in unavailable_dates:
            can_add = False
            reason = "Ești indisponibil în această zi"
        elif not my_reservations.empty:
            existing = my_reservations[
                (pd.to_datetime(my_reservations[COL_RES_DATE]).dt.date == selected_date)
            ]
            if not existing.empty:
                can_add = False
                reason = "Ai deja o rezervare în această zi"
        
        if can_add:
            if st.button("➕ Rezervă", type="primary", use_container_width=True):
                updated_reservations = add_reservation(doctor_id, selected_date, shift_type, reservations_df)
                save_data(SHEET_RESERVATIONS, updated_reservations)
                st.success("✅ Rezervare adăugată!")
                st.rerun()
        else:
            st.error(reason)
    
    # Vizualizare calendar lunar
    st.divider()
    
    # Luna curentă
    today = date.today()
    cal = calendar.monthcalendar(today.year, today.month)
    
    st.markdown(f"### {today.strftime('%B %Y')}")
    
    # Header zile
    cols = st.columns(7)
    for i, day_name in enumerate(['L', 'M', 'M', 'J', 'V', 'S', 'D']):
        with cols[i]:
            st.markdown(f"**{day_name}**")
    
    # Zile calendar
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day > 0:
                day_date = date(today.year, today.month, day)
                is_weekend = day_date.weekday() >= 5
                
                with cols[i]:
                    # Container pentru stilizare
                    style = ""
                    content = [f"**{day}**"]
                    
                    # Verifică statusuri
                    if day_date in unavailable_dates:
                        style = "background-color: #f8d7da; border-radius: 5px; padding: 5px;"
                        content.append("❌ Indisponibil")
                    elif not my_reservations.empty:
                        day_reservations = my_reservations[
                            pd.to_datetime(my_reservations[COL_RES_DATE]).dt.date == day_date
                        ]
                        for _, res in day_reservations.iterrows():
                            status_icon = "⏳" if res[COL_RES_STATUS] == 'pending' else "✅"
                            shift_label = SHIFT_TYPES[res[COL_RES_SHIFT]].split('(')[0]
                            content.append(f"{status_icon} {shift_label}")
                    
                    # Verifică program final
                    if not schedule_df.empty:
                        day_schedule = schedule_df[
                            pd.to_datetime(schedule_df[COL_DATE]).dt.date == day_date
                        ]
                        my_shifts = day_schedule[day_schedule[COL_DOC_ID] == doctor_id]
                        for _, shift in my_shifts.iterrows():
                            content.append(f"✅ {shift[COL_SHIFT].split('(')[0]}")
                    
                    if is_weekend:
                        style = "background-color: #fff3cd; border-radius: 5px; padding: 5px;"
                    
                    # Afișare
                    if style:
                        st.markdown(f'<div style="{style}">' + '<br>'.join(content) + '</div>', 
                                  unsafe_allow_html=True)
                    else:
                        for line in content:
                            st.markdown(line)

def show_my_reservations(doctor_id, reservations_df):
    """Afișează lista rezervărilor medicului."""
    my_reservations = get_doctor_reservations(doctor_id, reservations_df)
    
    if my_reservations.empty:
        st.info("Nu ai rezervări active.")
        return
    
    st.subheader("📋 Rezervările tale")
    
    # Sortează după dată
    my_reservations = my_reservations.sort_values(COL_RES_DATE)
    
    for idx, res in my_reservations.iterrows():
        col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
        
        res_date = pd.to_datetime(res[COL_RES_DATE])
        weekday = WEEKDAYS_RO[res_date.weekday()]
        
        with col1:
            st.write(f"**{weekday}, {res_date.strftime('%d.%m.%Y')}**")
        
        with col2:
            st.write(SHIFT_TYPES[res[COL_RES_SHIFT]])
        
        with col3:
            status_map = {
                'pending': '⏳ În așteptare',
                'approved': '✅ Aprobat',
                'rejected': '❌ Respins'
            }
            st.write(status_map.get(res[COL_RES_STATUS], res[COL_RES_STATUS]))
        
        with col4:
            if res[COL_RES_STATUS] == 'pending':
                if st.button("🗑️", key=f"del_res_{idx}"):
                    reservations_df = reservations_df.drop(idx)
                    save_data(SHEET_RESERVATIONS, reservations_df)
                    st.rerun()

# ──────────────────────────────────────────────────────────
# Funcții Manager
# ──────────────────────────────────────────────────────────
def resolve_conflicts_and_generate(reservations_df, doctors_df, start_date, end_date, priorities_df):
    """Rezolvă conflictele și generează programul final."""
    schedule_rows = []
    
    # Grupează rezervările pe date
    if not reservations_df.empty:
        reservations_df['date_obj'] = pd.to_datetime(reservations_df[COL_RES_DATE])
        pending_reservations = reservations_df[reservations_df[COL_RES_STATUS] == 'pending']
    else:
        pending_reservations = pd.DataFrame()
    
    # Pentru fiecare zi din perioada selectată
    current_date = start_date
    while current_date <= end_date:
        # Găsește toate rezervările pentru această zi
        if not pending_reservations.empty:
            day_reservations = pending_reservations[
                pending_reservations['date_obj'].dt.date == current_date
            ]
        else:
            day_reservations = pd.DataFrame()
        
        # Procesează fiecare tip de gardă
        for shift_key, shift_name in SHIFT_TYPES.items():
            if not day_reservations.empty:
                shift_requests = day_reservations[day_reservations[COL_RES_SHIFT] == shift_key]
            else:
                shift_requests = pd.DataFrame()
            
            if len(shift_requests) == 0:
                # Nu există rezervări - va fi completat automat mai târziu
                continue
            elif len(shift_requests) == 1:
                # O singură cerere - aprobată automat
                selected_doc = shift_requests.iloc[0][COL_RES_DOC]
                schedule_rows.append({
                    COL_DATE: current_date.strftime('%Y-%m-%d'),
                    COL_SHIFT: shift_name,
                    COL_DOC_ID: selected_doc
                })
                
                # Actualizează status rezervare
                idx = shift_requests.index[0]
                reservations_df.loc[idx, COL_RES_STATUS] = 'approved'
            else:
                # Multiple cereri - rezolvare conflict
                # Calculează prioritățile
                month_key = f"{current_date.year}-{current_date.month:02d}"
                candidates = []
                
                for _, req in shift_requests.iterrows():
                    doc_id = req[COL_RES_DOC]
                    
                    # Obține scorul de prioritate
                    if not priorities_df.empty:
                        doc_priority = priorities_df[
                            (priorities_df[COL_PRIO_DOC] == doc_id) & 
                            (priorities_df[COL_PRIO_MONTH] == month_key)
                        ]
                        priority_score = doc_priority[COL_PRIO_SCORE].iloc[0] if not doc_priority.empty else 0
                    else:
                        priority_score = 0
                    
                    candidates.append((doc_id, priority_score))
                
                # Sortează după prioritate (descrescător) și alege random dintre cei cu prioritate egală
                candidates.sort(key=lambda x: x[1], reverse=True)
                max_priority = candidates[0][1]
                top_candidates = [c[0] for c in candidates if c[1] == max_priority]
                
                # Alege random dintre candidații cu prioritate maximă
                selected_doc = random.choice(top_candidates)
                
                schedule_rows.append({
                    COL_DATE: current_date.strftime('%Y-%m-%d'),
                    COL_SHIFT: shift_name,
                    COL_DOC_ID: selected_doc
                })
                
                # Actualizează statusuri
                for _, req in shift_requests.iterrows():
                    idx = shift_requests[shift_requests[COL_RES_DOC] == req[COL_RES_DOC]].index[0]
                    if req[COL_RES_DOC] == selected_doc:
                        reservations_df.loc[idx, COL_RES_STATUS] = 'approved'
                    else:
                        reservations_df.loc[idx, COL_RES_STATUS] = 'rejected'
                        # Crește prioritatea pentru luna viitoare
                        update_priority(req[COL_RES_DOC], current_date, priorities_df, increase=True)
        
        current_date += timedelta(days=1)
    
    return pd.DataFrame(schedule_rows), reservations_df, priorities_df

def update_priority(doctor_id, date_obj, priorities_df, increase=True):
    """Actualizează prioritatea unui medic."""
    next_month = (date_obj.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_key = f"{next_month.year}-{next_month.month:02d}"
    
    if priorities_df.empty:
        priorities_df = pd.DataFrame(columns=[COL_PRIO_DOC, COL_PRIO_MONTH, COL_PRIO_SCORE])
    
    # Găsește sau creează înregistrarea
    mask = (priorities_df[COL_PRIO_DOC] == doctor_id) & (priorities_df[COL_PRIO_MONTH] == month_key)
    
    if mask.any():
        if increase:
            priorities_df.loc[mask, COL_PRIO_SCORE] += 1
        else:
            priorities_df.loc[mask, COL_PRIO_SCORE] -= 1
    else:
        new_priority = pd.DataFrame([{
            COL_PRIO_DOC: doctor_id,
            COL_PRIO_MONTH: month_key,
            COL_PRIO_SCORE: 1 if increase else 0
        }])
        priorities_df = pd.concat([priorities_df, new_priority], ignore_index=True)
    
    return priorities_df

def fill_empty_shifts(schedule_df, doctors_df, start_date, end_date, unavail_df):
    """Completează automat gărzile nerezervate."""
    # Obține toate datele și tipurile de gărzi necesare
    all_dates = pd.date_range(start_date, end_date)
    
    # Pentru fiecare zi verifică ce lipsește
    for current_date in all_dates:
        # Determină ce ture sunt necesare
        if current_date.weekday() < 5:  # Zi lucrătoare
            required_shifts = ["Gardă 24h"]  # Sau configurabil
        else:
            required_shifts = ["Gardă 24h"]
        
        # Verifică ce există deja
        if not schedule_df.empty:
            existing = schedule_df[
                pd.to_datetime(schedule_df[COL_DATE]).dt.date == current_date.date()
            ]
            existing_shifts = existing[COL_SHIFT].tolist()
        else:
            existing_shifts = []
        
        # Completează ce lipsește
        for shift in required_shifts:
            if shift not in existing_shifts:
                # Găsește un medic disponibil
                available_doctors = []
                
                for _, doc in doctors_df.iterrows():
                    doc_id = doc[COL_ID]
                    
                    # Verifică indisponibilitate
                    if not unavail_df.empty:
                        is_unavailable = any(
                            (unavail_df['doctor_id'] == doc_id) & 
                            (pd.to_datetime(unavail_df['date']).dt.date == current_date.date())
                        )
                        if is_unavailable:
                            continue
                    
                    # Verifică limita lunară
                    month_shifts = 0
                    if not schedule_df.empty:
                        month_mask = (
                            (schedule_df[COL_DOC_ID] == doc_id) &
                            (pd.to_datetime(schedule_df[COL_DATE]).dt.month == current_date.month) &
                            (pd.to_datetime(schedule_df[COL_DATE]).dt.year == current_date.year)
                        )
                        month_shifts = len(schedule_df[month_mask])
                    
                    if month_shifts < doc[COL_MAX]:
                        available_doctors.append(doc_id)
                
                # Alege un medic disponibil
                if available_doctors:
                    selected_doc = random.choice(available_doctors)
                    new_shift = pd.DataFrame([{
                        COL_DATE: current_date.strftime('%Y-%m-%d'),
                        COL_SHIFT: shift,
                        COL_DOC_ID: selected_doc
                    }])
                    
                    if schedule_df.empty:
                        schedule_df = new_shift
                    else:
                        schedule_df = pd.concat([schedule_df, new_shift], ignore_index=True)
    
    return schedule_df

def show_manager_calendar_allocation(schedule_df, doctors_df):
    """Interfață calendar pentru alocare manuală."""
    st.subheader("📅 Alocare Manuală prin Calendar")
    
    # Selectori principali
    col1, col2 = st.columns(2)
    
    with col1:
        selected_date = st.date_input(
            "Selectează data:",
            value=date.today(),
            min_value=date.today()
        )
    
    with col2:
        shift_type = st.selectbox(
            "Tip gardă:",
            options=list(SHIFT_TYPES.values())
        )
    
    # Verifică ce există deja pentru această dată
    if not schedule_df.empty:
        existing = schedule_df[
            (pd.to_datetime(schedule_df[COL_DATE]).dt.date == selected_date) &
            (schedule_df[COL_SHIFT] == shift_type)
        ]
        
        if not existing.empty:
            current_doc = existing.iloc[0][COL_DOC_ID]
            st.warning(f"⚠️ Gardă deja alocată pentru {selected_date.strftime('%d.%m.%Y')}")
        else:
            current_doc = None
    else:
        current_doc = None
    
    # Selector medic
    if not doctors_df.empty:
        doctor_options = {
            f"{doc[COL_NAME]} - {doc[COL_SPEC]}": doc[COL_ID]
            for _, doc in doctors_df.iterrows()
        }
        
        if current_doc:
            current_doc_name = next(
                (name for name, id in doctor_options.items() if id == current_doc),
                None
            )
            default_index = list(doctor_options.keys()).index(current_doc_name) if current_doc_name else 0
        else:
            default_index = 0
        
        selected_doc_display = st.selectbox(
            "Alege medicul:",
            options=list(doctor_options.keys()),
            index=default_index
        )
        selected_doc_id = doctor_options[selected_doc_display]
        
        # Butoane acțiune
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("💾 Salvează/Actualizează", type="primary", use_container_width=True):
                # Elimină intrarea existentă dacă există
                if not schedule_df.empty:
                    schedule_df = schedule_df[
                        ~((pd.to_datetime(schedule_df[COL_DATE]).dt.date == selected_date) &
                          (schedule_df[COL_SHIFT] == shift_type))
                    ]
                
                # Adaugă noua intrare
                new_entry = pd.DataFrame([{
                    COL_DATE: selected_date.strftime('%Y-%m-%d'),
                    COL_SHIFT: shift_type,
                    COL_DOC_ID: selected_doc_id
                }])
                
                if schedule_df.empty:
                    schedule_df = new_entry
                else:
                    schedule_df = pd.concat([schedule_df, new_entry], ignore_index=True)
                
                save_data(SHEET_SCHEDULE, schedule_df)
                st.success("✅ Gardă salvată!")
                st.rerun()
        
        with col2:
            if current_doc and st.button("🗑️ Șterge", use_container_width=True):
                schedule_df = schedule_df[
                    ~((pd.to_datetime(schedule_df[COL_DATE]).dt.date == selected_date) &
                      (schedule_df[COL_SHIFT] == shift_type))
                ]
                save_data(SHEET_SCHEDULE, schedule_df)
                st.success("✅ Gardă ștearsă!")
                st.rerun()

# ──────────────────────────────────────────────────────────
# Vizualizare simplificată
# ──────────────────────────────────────────────────────────
def show_schedule_view(schedule_df, doctors_df, start_date, end_date):
    """Afișează programul într-un format tabel clar."""
    if schedule_df.empty:
        st.info("Nu există program generat.")
        return
    
    # Filtrează pentru perioada selectată
    schedule_df['date_obj'] = pd.to_datetime(schedule_df[COL_DATE])
    mask = (schedule_df['date_obj'].dt.date >= start_date) & (schedule_df['date_obj'].dt.date <= end_date)
    filtered = schedule_df[mask].copy()
    
    if filtered.empty:
        st.info("Nu există gărzi în perioada selectată.")
        return
    
    # Mapare ID -> Nume
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    filtered['Medic'] = filtered[COL_DOC_ID].map(id_to_name)
    
    # Formatare date
    filtered['Data'] = filtered['date_obj'].dt.strftime('%d.%m.%Y')
    filtered['Zi'] = filtered['date_obj'].apply(lambda x: WEEKDAYS_RO[x.weekday()])
    filtered['Weekend'] = filtered['date_obj'].dt.weekday >= 5
    
    # Sortare
    filtered = filtered.sort_values('date_obj')
    
    # Afișare cu stilizare pentru weekend
    for _, row in filtered.iterrows():
        col1, col2, col3, col4 = st.columns([1, 2, 2, 3])
        
        with col1:
            if row['Weekend']:
                st.markdown(f"**🟡 {row['Zi'][:3]}**")
            else:
                st.write(row['Zi'][:3])
        
        with col2:
            st.write(row['Data'])
        
        with col3:
            # Icon pentru tip gardă
            if "24h" in row[COL_SHIFT]:
                st.write("🔴 " + row[COL_SHIFT])
            elif "Zi" in row[COL_SHIFT]:
                st.write("🟢 " + row[COL_SHIFT])
            else:
                st.write("🔵 " + row[COL_SHIFT])
        
        with col4:
            st.write(f"**{row['Medic']}**")
        
        st.divider()

# ──────────────────────────────────────────────────────────
# Aplicația principală  
# ──────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="🩺 Planificare Gărzi - Rezervări",
        page_icon="🏥",
        layout="wide"
    )
    
    # Verifică autentificarea
    if not check_auth():
        show_login()
        return
    
    # Configurare spital
    sheet_id = select_hospital()
    st.session_state["sheet_id"] = sheet_id
    
    # Header cu rol și logout
    col1, col2, col3 = st.columns([6, 1, 1])
    with col1:
        hospitals = get_hospital_config()
        hospital_name = hospitals.get(
            st.session_state.get('selected_hospital', 'default'), {}
        ).get('name', 'Spital')
        st.title(f"🏥 Planificare Gărzi - {hospital_name}")
    
    with col2:
        role = st.session_state.get('user_role', '')
        if role == 'doctor':
            st.write(f"👨‍⚕️ Dr. {st.session_state.get('doctor_name', '')}")
        else:
            st.write("👨‍💼 Manager")
    
    with col3:
        if st.button("🚪 Ieșire"):
            logout()
    
    # Încarcă datele
    doctors_df = load_data(SHEET_DOCTORS)
    schedule_df = load_data(SHEET_SCHEDULE)
    reservations_df = load_data(SHEET_RESERVATIONS)
    priorities_df = load_data(SHEET_PRIORITIES)
    unavail_df = load_data(SHEET_UNAVAILABLE)
    
    # Curățare date
    if not doctors_df.empty:
        doctors_df[COL_ID] = pd.to_numeric(doctors_df[COL_ID], errors='coerce').fillna(0).astype(int)
        doctors_df = doctors_df[doctors_df[COL_ID] > 0]
        doctors_df[COL_MAX] = pd.to_numeric(doctors_df[COL_MAX], errors='coerce').fillna(8).astype(int)
    
    # Interfață bazată pe rol
    if st.session_state['user_role'] == 'doctor':
        # INTERFAȚĂ MEDIC
        tabs = st.tabs(["📅 Rezervări", "📋 Rezervările Mele", "🚫 Indisponibilități", "📊 Program Final"])
        
        with tabs[0]:
            show_reservation_calendar(
                st.session_state['doctor_id'],
                st.session_state['doctor_name'],
                reservations_df,
                unavail_df,
                schedule_df
            )
        
        with tabs[1]:
            show_my_reservations(st.session_state['doctor_id'], reservations_df)
        
        with tabs[2]:
            st.subheader("🚫 Marchează Indisponibilități")
            st.info("Selectează zilele când NU poți lua gărzi")
            
            # Calendar pentru indisponibilități
            selected_dates = st.date_input(
                "Selectează datele:",
                value=[],
                min_value=date.today(),
                max_value=date.today() + timedelta(days=90),
                key="unavail_dates"
            )
            
            if st.button("💾 Salvează Indisponibilități"):
                # Șterge indisponibilitățile vechi
                if not unavail_df.empty:
                    unavail_df = unavail_df[unavail_df['doctor_id'] != st.session_state['doctor_id']]
                
                # Adaugă cele noi
                for sel_date in selected_dates:
                    new_unavail = pd.DataFrame([{
                        'doctor_id': st.session_state['doctor_id'],
                        'date': sel_date.strftime('%Y-%m-%d'),
                        'reason': 'Indisponibil'
                    }])
                    
                    if unavail_df.empty:
                        unavail_df = new_unavail
                    else:
                        unavail_df = pd.concat([unavail_df, new_unavail], ignore_index=True)
                
                save_data(SHEET_UNAVAILABLE, unavail_df)
                st.success("✅ Indisponibilități salvate!")
                st.rerun()
        
        with tabs[3]:
            st.subheader("📊 Program Final")
            
            if not schedule_df.empty:
                my_shifts = schedule_df[schedule_df[COL_DOC_ID] == st.session_state['doctor_id']]
                
                if not my_shifts.empty:
                    my_shifts = my_shifts.sort_values(COL_DATE)
                    
                    st.metric("Total gărzi:", len(my_shifts))
                    
                    for _, shift in my_shifts.iterrows():
                        shift_date = pd.to_datetime(shift[COL_DATE])
                        weekday = WEEKDAYS_RO[shift_date.weekday()]
                        
                        col1, col2, col3 = st.columns([2, 1, 2])
                        with col1:
                            st.write(f"**{weekday}, {shift_date.strftime('%d.%m.%Y')}**")
                        with col2:
                            if shift_date.weekday() >= 5:
                                st.write("🟡 Weekend")
                        with col3:
                            st.write(shift[COL_SHIFT])
                else:
                    st.info("Nu ai gărzi alocate încă.")
            else:
                st.info("Programul final nu a fost generat încă.")
    
    else:  # MANAGER
        # INTERFAȚĂ MANAGER
        with st.sidebar:
            st.header("⚙️ Opțiuni Manager")
            
            # Generare automată
            st.subheader("🤖 Generare Automată")
            
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("De la:", value=date.today())
            with col2:
                end_date = st.date_input("Până la:", value=date.today() + timedelta(days=30))
            
            if st.button("🚀 Generează Program", type="primary", use_container_width=True):
                with st.spinner("Procesez rezervările și generez programul..."):
                    # 1. Rezolvă conflictele din rezervări
                    schedule_df, updated_reservations, updated_priorities = resolve_conflicts_and_generate(
                        reservations_df, doctors_df, start_date, end_date, priorities_df
                    )
                    
                    # 2. Completează gărzile lipsă
                    schedule_df = fill_empty_shifts(
                        schedule_df, doctors_df, start_date, end_date, unavail_df
                    )
                    
                    # 3. Salvează toate modificările
                    save_data(SHEET_SCHEDULE, schedule_df)
                    save_data(SHEET_RESERVATIONS, updated_reservations)
                    save_data(SHEET_PRIORITIES, updated_priorities)
                    
                    st.success("✅ Program generat cu succes!")
                    st.balloons()
                    st.rerun()
            
            # Export
            st.divider()
            if not schedule_df.empty:
                # Generare text export
                export_text = "PROGRAM GĂRZI MEDICALE\n"
                export_text += "=" * 50 + "\n\n"
                export_text += f"Generat: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                
                id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
                schedule_sorted = schedule_df.sort_values(COL_DATE)
                
                for _, row in schedule_sorted.iterrows():
                    date_obj = pd.to_datetime(row[COL_DATE])
                    weekday = WEEKDAYS_RO[date_obj.weekday()]
                    doc_name = id_to_name.get(row[COL_DOC_ID], "Necunoscut")
                    export_text += f"{weekday}, {date_obj.strftime('%d.%m.%Y')} - {row[COL_SHIFT]}: {doc_name}\n"
                
                st.download_button(
                    "📥 Export .txt",
                    export_text,
                    f"program_{date.today()}.txt",
                    "text/plain",
                    use_container_width=True
                )
        
        # Tabs manager
        tabs = st.tabs([
            "📅 Program", 
            "🔧 Alocare Manuală",
            "📋 Rezervări",
            "👨‍⚕️ Personal",
            "📊 Statistici"
        ])
        
        with tabs[0]:
            st.header("📅 Vizualizare Program")
            
            col1, col2 = st.columns(2)
            with col1:
                view_start = st.date_input("De la:", value=date.today())
            with col2:
                view_end = st.date_input("Până la:", value=date.today() + timedelta(days=14))
            
            show_schedule_view(schedule_df, doctors_df, view_start, view_end)
        
        with tabs[1]:
            show_manager_calendar_allocation(schedule_df, doctors_df)
        
        with tabs[2]:
            st.header("📋 Gestionare Rezervări")
            
            if not reservations_df.empty:
                # Filtrare după status
                status_filter = st.selectbox(
                    "Filtrează după status:",
                    ["Toate", "În așteptare", "Aprobate", "Respinse"],
                    index=0
                )
                
                if status_filter == "În așteptare":
                    filtered_res = reservations_df[reservations_df[COL_RES_STATUS] == 'pending']
                elif status_filter == "Aprobate":
                    filtered_res = reservations_df[reservations_df[COL_RES_STATUS] == 'approved']
                elif status_filter == "Respinse":
                    filtered_res = reservations_df[reservations_df[COL_RES_STATUS] == 'rejected']
                else:
                    filtered_res = reservations_df
                
                if not filtered_res.empty:
                    # Adaugă nume medici
                    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
                    filtered_res['Medic'] = filtered_res[COL_RES_DOC].map(id_to_name)
                    filtered_res['Data'] = pd.to_datetime(filtered_res[COL_RES_DATE]).dt.strftime('%d.%m.%Y')
                    filtered_res['Gardă'] = filtered_res[COL_RES_SHIFT].map(SHIFT_TYPES)
                    
                    # Afișare
                    st.dataframe(
                        filtered_res[['Data', 'Medic', 'Gardă', COL_RES_STATUS]],
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("Nu există rezervări pentru acest filtru.")
            else:
                st.info("Nu există rezervări.")
        
        with tabs[3]:
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
            
            if st.button("💾 Salvează Modificări", type="primary"):
                if edited[COL_ID].duplicated().any():
                    st.error("❌ Există ID-uri duplicate!")
                else:
                    save_data(SHEET_DOCTORS, edited)
                    st.success("✅ Lista salvată!")
                    st.rerun()
        
        with tabs[4]:
            st.header("📊 Statistici")
            
            if not schedule_df.empty:
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Total Gărzi", len(schedule_df))
                
                with col2:
                    unique_docs = schedule_df[COL_DOC_ID].nunique()
                    st.metric("Medici Activi", unique_docs)
                
                with col3:
                    if not reservations_df.empty:
                        pending = len(reservations_df[reservations_df[COL_RES_STATUS] == 'pending'])
                        st.metric("Rezervări În Așteptare", pending)
                
                with col4:
                    weekend_shifts = len(schedule_df[
                        pd.to_datetime(schedule_df[COL_DATE]).dt.weekday >= 5
                    ])
                    st.metric("Gărzi Weekend", weekend_shifts)
                
                # Distribuție pe medici
                st.divider()
                st.subheader("Distribuție Gărzi")
                
                stats = schedule_df[COL_DOC_ID].value_counts()
                id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
                
                stats_df = pd.DataFrame({
                    'Medic': [id_to_name.get(doc_id, f"ID {doc_id}") for doc_id in stats.index],
                    'Total': stats.values
                })
                
                st.bar_chart(stats_df.set_index('Medic'))

if __name__ == "__main__":
    main()
