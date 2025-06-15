#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistem Simplificat de Planificare Gărzi Medicale
Versiune: 6.0 - Algoritm Round-Robin Standard
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict
import io

# ──────────────────────────────────────────────────────────
# CONFIGURARE ȘI CONSTANTE
# ──────────────────────────────────────────────────────────
# Nume foi în Google Sheets
SHEET_DOCTORS = "Doctors"
SHEET_SCHEDULE = "Schedule"
SHEET_UNAVAILABLE = "Unavailable"
SHEET_PREFERENCES = "Preferences"

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
COL_UNAV_DOC = "doctor_id"
COL_UNAV_DATE = "date"
COL_UNAV_REASON = "reason"
COL_PREF_DOC = "doctor_id"
COL_PREF_DAY = "preferred_day"
COL_PREF_SHIFT = "preferred_shift"

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
SHIFT_TYPES = {
    1: ["Gardă 24h"],
    2: ["Gardă Zi (08-20)", "Gardă Noapte (20-08)"]
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
    """Permite selectarea spitalului și returnează sheet_id."""
    hospitals = get_hospital_config()
    keys = list(hospitals.keys())
    
    if len(keys) == 1:
        st.session_state["selected_hospital"] = keys[0]
        return hospitals[keys[0]]["sheet_id"]
    
    # Selector în sidebar pentru mai multe spitale
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
# Funcții Google Sheets simplificate
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
        
        # Creează sau golește foaia
        try:
            worksheet = sh.worksheet(sheet_name)
            worksheet.clear()
        except:
            worksheet = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)
        
        # Salvează datele
        if not df.empty:
            headers = df.columns.tolist()
            values = df.fillna('').astype(str).values.tolist()
            data = [headers] + values
            worksheet.update(data, value_input_option='USER_ENTERED')
            
    except Exception as e:
        st.error(f"❌ Eroare salvare: {str(e)}")

# ──────────────────────────────────────────────────────────
# Algoritm simplificat Round-Robin
# ──────────────────────────────────────────────────────────
def generate_simple_schedule(doctors_df, start_date, end_date, shift_type, speciality_filter=None):
    """
    Generează program folosind algoritm Round-Robin standard.
    Acesta este cel mai folosit algoritm în spitale pentru echitate.
    """
    if doctors_df.empty:
        st.error("❌ Nu există personal înregistrat!")
        return pd.DataFrame()
    
    # Filtrare pe specialitate dacă e cazul
    if speciality_filter and speciality_filter != "Toate":
        available_doctors = doctors_df[doctors_df[COL_SPEC] == speciality_filter].copy()
        if available_doctors.empty:
            st.error(f"❌ Nu există personal cu specialitatea {speciality_filter}!")
            return pd.DataFrame()
    else:
        available_doctors = doctors_df.copy()
    
    # Pregătește lista de medici și contoare
    doctor_ids = available_doctors[COL_ID].tolist()
    if not doctor_ids:
        return pd.DataFrame()
    
    # Inițializează contoare
    shifts_count = defaultdict(int)
    max_shifts = dict(zip(available_doctors[COL_ID], available_doctors[COL_MAX]))
    
    # Tipuri de ture pentru ziua respectivă
    shifts = SHIFT_TYPES[shift_type]
    
    # Generare program
    schedule_rows = []
    current_date = start_date
    doctor_index = 0  # Pentru round-robin
    
    while current_date <= end_date:
        for shift_name in shifts:
            # Găsește următorul medic disponibil (round-robin)
            attempts = 0
            assigned = False
            
            while attempts < len(doctor_ids) and not assigned:
                doc_id = doctor_ids[doctor_index % len(doctor_ids)]
                
                # Verifică dacă poate lua garda
                month_key = f"{current_date.year}-{current_date.month}"
                if shifts_count[f"{doc_id}_{month_key}"] < max_shifts.get(doc_id, 8):
                    # Atribuie garda
                    schedule_rows.append({
                        COL_DATE: current_date.strftime('%Y-%m-%d'),
                        COL_SHIFT: shift_name,
                        COL_DOC_ID: doc_id
                    })
                    shifts_count[f"{doc_id}_{month_key}"] += 1
                    assigned = True
                
                doctor_index += 1
                attempts += 1
            
            if not assigned:
                st.warning(f"⚠️ Nu s-a putut atribui gardă pentru {current_date.strftime('%d.%m.%Y')} - {shift_name}")
        
        current_date += timedelta(days=1)
    
    return pd.DataFrame(schedule_rows)

# ──────────────────────────────────────────────────────────
# Funcții de afișare simplificate
# ──────────────────────────────────────────────────────────
def show_schedule_table(schedule_df, doctors_df):
    """Afișează programul ca tabel simplu."""
    if schedule_df.empty:
        st.info("📅 Nu există program generat.")
        return
    
    # Mapare ID -> Nume
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    
    # Pregătește datele pentru afișare
    display_df = schedule_df.copy()
    display_df['Medic'] = display_df[COL_DOC_ID].map(id_to_name).fillna("Necunoscut")
    display_df['Data'] = pd.to_datetime(display_df[COL_DATE]).dt.strftime('%d.%m.%Y (%A)')
    display_df['Tură'] = display_df[COL_SHIFT]
    
    # Afișează tabelul
    st.dataframe(
        display_df[['Data', 'Tură', 'Medic']],
        use_container_width=True,
        hide_index=True,
        height=600
    )

def export_schedule_text(schedule_df, doctors_df):
    """Exportă programul ca fișier text simplu."""
    if schedule_df.empty:
        return ""
    
    # Mapare ID -> Nume
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    
    # Construiește textul
    text = "PROGRAM GĂRZI MEDICALE\n"
    text += "=" * 50 + "\n\n"
    text += f"Generat la: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
    
    # Sortează pe date
    schedule_df_sorted = schedule_df.sort_values(COL_DATE)
    
    current_date = None
    for _, row in schedule_df_sorted.iterrows():
        date_str = row[COL_DATE]
        
        # Header pentru zi nouă
        if date_str != current_date:
            current_date = date_str
            date_obj = pd.to_datetime(date_str)
            weekday = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică'][date_obj.weekday()]
            text += f"\n{weekday}, {date_obj.strftime('%d.%m.%Y')}\n"
            text += "-" * 30 + "\n"
        
        # Detalii gardă
        doc_name = id_to_name.get(row[COL_DOC_ID], "Necunoscut")
        text += f"  {row[COL_SHIFT]}: {doc_name}\n"
    
    # Statistici la final
    text += "\n\nSTATISTICI\n"
    text += "=" * 50 + "\n"
    
    stats = schedule_df.groupby(COL_DOC_ID).size()
    for doc_id, count in stats.items():
        doc_name = id_to_name.get(doc_id, f"ID {doc_id}")
        text += f"{doc_name}: {count} gărzi\n"
    
    return text

# ──────────────────────────────────────────────────────────
# Aplicația principală
# ──────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="🩺 Planificare Gărzi - Simplificat",
        page_icon="🏥",
        layout="wide"
    )
    
    # Selectare spital
    sheet_id = select_hospital()
    st.session_state["sheet_id"] = sheet_id
    
    # Header
    hospitals = get_hospital_config()
    hospital_name = hospitals.get(
        st.session_state.get('selected_hospital', 'default'), 
        {}
    ).get('name', 'Spital')
    
    st.title(f"🏥 Planificare Gărzi - {hospital_name}")
    st.caption("Sistem simplificat cu algoritm Round-Robin")
    
    # Încarcă datele
    doctors_df = load_data(SHEET_DOCTORS)
    schedule_df = load_data(SHEET_SCHEDULE)
    
    # Curățare date medici
    if not doctors_df.empty:
        # Asigură coloanele necesare
        for col in [COL_ID, COL_NAME, COL_SPEC, COL_MAX]:
            if col not in doctors_df.columns:
                doctors_df[col] = ""
        
        # Conversii de tip sigure
        doctors_df[COL_ID] = pd.to_numeric(doctors_df[COL_ID], errors='coerce').fillna(0).astype(int)
        doctors_df = doctors_df[doctors_df[COL_ID] > 0]
        doctors_df[COL_MAX] = pd.to_numeric(doctors_df[COL_MAX], errors='coerce').fillna(8).astype(int)
    
    # Sidebar pentru generare
    with st.sidebar:
        st.header("⚙️ Generare Program")
        
        # Verificare personal
        if doctors_df.empty:
            st.error("❌ Nu există personal!")
            st.info("Adaugă personal în tab-ul corespunzător")
        else:
            st.success(f"✅ {len(doctors_df)} medici disponibili")
        
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
        
        # Filtru specialitate - NOUĂ FUNCȚIONALITATE
        st.subheader("👨‍⚕️ Filtru Specialitate")
        speciality_options = ["Toate"] + SPECIALTIES
        selected_speciality = st.selectbox(
            "Generează gărzi doar pentru:",
            options=speciality_options,
            help="Selectează o specialitate pentru a genera gărzi doar pentru acea categorie"
        )
        
        # Buton generare
        if st.button("🚀 Generează Program", type="primary", use_container_width=True):
            if start_date <= end_date:
                with st.spinner("Generez programul..."):
                    new_schedule = generate_simple_schedule(
                        doctors_df, 
                        start_date, 
                        end_date, 
                        shift_type,
                        selected_speciality if selected_speciality != "Toate" else None
                    )
                    
                    if not new_schedule.empty:
                        save_data(SHEET_SCHEDULE, new_schedule)
                        st.success("✅ Program generat cu succes!")
                        st.rerun()
            else:
                st.error("❌ Data de început trebuie să fie înainte de cea de sfârșit!")
    
    # Tabs principale
    tab1, tab2, tab3, tab4 = st.tabs([
        "📅 Program",
        "👨‍⚕️ Personal", 
        "🚫 Indisponibilități",
        "📊 Statistici"
    ])
    
    with tab1:
        st.header("📅 Program Gărzi")
        
        if not schedule_df.empty:
            # Curățare date program pentru afișare sigură
            if COL_DATE in schedule_df.columns:
                # Convertește datele la string mai întâi pentru siguranță
                schedule_df[COL_DATE] = schedule_df[COL_DATE].astype(str)
            
            # Afișare tabel
            show_schedule_table(schedule_df, doctors_df)
            
            # Export text
            st.divider()
            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader("📤 Export Program")
            with col2:
                text_content = export_schedule_text(schedule_df, doctors_df)
                st.download_button(
                    "📥 Descarcă .txt",
                    text_content,
                    f"program_garzi_{date.today()}.txt",
                    "text/plain",
                    use_container_width=True
                )
        else:
            st.info("Nu există program generat. Folosește panoul din stânga pentru a genera unul.")
    
    with tab2:
        st.header("👨‍⚕️ Gestionare Personal")
        
        # Pregătește DataFrame pentru editor
        if doctors_df.empty:
            # Creează DataFrame gol cu structura corectă
            doctors_df = pd.DataFrame(columns=[COL_ID, COL_NAME, COL_SPEC, COL_MAX, COL_PHONE, COL_EMAIL])
        
        # Editor
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
        
        # Salvare
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("💾 Salvează", type="primary", use_container_width=True):
                # Validare ID-uri unice
                if edited[COL_ID].duplicated().any():
                    st.error("❌ Există ID-uri duplicate!")
                else:
                    save_data(SHEET_DOCTORS, edited)
                    st.success("✅ Lista salvată!")
                    st.rerun()
    
    with tab3:
        st.header("🚫 Indisponibilități")
        st.info("💡 Funcționalitate în dezvoltare. Pentru moment, gestionați manual indisponibilitățile.")
        
        # TODO: Implementare simplă pentru indisponibilități
        st.markdown("""
        ### Cum să gestionați indisponibilitățile:
        1. Generați programul normal
        2. Modificați manual în foaia Google Sheets pentru zilele de concediu
        3. Sau contactați administratorul pentru ajustări
        """)
    
    with tab4:
        st.header("📊 Statistici Simple")
        
        if not schedule_df.empty:
            # Statistici de bază
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Gărzi", len(schedule_df))
            
            with col2:
                unique_docs = schedule_df[COL_DOC_ID].nunique()
                st.metric("Medici Activi", unique_docs)
            
            with col3:
                if COL_DATE in schedule_df.columns:
                    try:
                        dates = pd.to_datetime(schedule_df[COL_DATE], errors='coerce')
                        date_range = f"{dates.min().strftime('%d.%m')} - {dates.max().strftime('%d.%m')}"
                        st.metric("Perioadă", date_range)
                    except:
                        st.metric("Perioadă", "N/A")
            
            # Distribuție pe medici
            st.subheader("Distribuție Gărzi")
            if COL_DOC_ID in schedule_df.columns:
                stats = schedule_df[COL_DOC_ID].value_counts()
                
                # Adaugă numele medicilor
                id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
                stats_with_names = pd.DataFrame({
                    'Medic': [id_to_name.get(doc_id, f"ID {doc_id}") for doc_id in stats.index],
                    'Număr Gărzi': stats.values
                })
                
                # Grafic simplu
                st.bar_chart(stats_with_names.set_index('Medic'))
                
                # Tabel detaliat
                st.dataframe(stats_with_names, use_container_width=True, hide_index=True)
        else:
            st.info("Nu există date pentru statistici.")

# ──────────────────────────────────────────────────────────
# Rulare aplicație
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
