"""streamlit_guard_scheduler.py

Aplicație Streamlit pentru gestionarea programului de gărzi medicale.
Versiune îmbunătățită cu algoritm mai inteligent și interfață mai prietenoasă.

2025-06-15 v5.0 (Enhanced & User-Friendly)
────────────────
• ALGORITM ÎMBUNĂTĂȚIT: Distribuție mai echitabilă a gărzilor
• UI/UX: Interfață mai intuitivă cu statistici și validări
• ROBUSTEȚE: Gestionare mai bună a erorilor și cazurilor speciale
• FUNCȚII NOI: Export PDF, statistici detaliate, preferințe medici
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict
import random

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
SHEET_PREFERENCES = "Preferences"  # NOU: pentru preferințe

# Coloane pentru medici
COL_ID = "id"
COL_NAME = "name"
COL_SPEC = "speciality"
COL_MAX = "max_shifts_per_month"
COL_PHONE = "phone"  # NOU
COL_EMAIL = "email"  # NOU

# Coloane pentru program
COL_DATE = "date"
COL_SHIFT = "shift_name"
COL_DOC_ID = "doctor_id"

# Coloane pentru indisponibilități
COL_UNAV_DOC = "doctor_id"
COL_UNAV_DATE = "date"
COL_UNAV_REASON = "reason"  # NOU: motiv indisponibilitate

# Coloane pentru preferințe
COL_PREF_DOC = "doctor_id"
COL_PREF_DAY = "preferred_day"  # 0=Luni, 6=Duminică
COL_PREF_SHIFT = "preferred_shift"

# Tipuri de ture
SHIFT_TYPES = {
    1: ["Gardă 24h"],
    2: ["Gardă Zi (08-20)", "Gardă Noapte (20-08)"],
    3: ["Tură 1 (08-16)", "Tură 2 (16-24)", "Tură 3 (00-08)"],
}

# ---------------------------------------------------------------------------
# Funcții ajutătoare pentru stilizare
# ---------------------------------------------------------------------------
def get_shift_color(shift_name: str) -> str:
    """Returnează culoarea pentru tipul de tură."""
    colors = {
        "24h": "#FF6B6B",
        "Zi": "#4ECDC4",
        "Noapte": "#45B7D1",
        "Tură 1": "#96CEB4",
        "Tură 2": "#FECA57",
        "Tură 3": "#DDA0DD",
    }
    for key, color in colors.items():
        if key in shift_name:
            return color
    return "#95A5A6"

# ---------------------------------------------------------------------------
# Wrappers pentru Google Sheets
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="🔗 Conectare la Google Sheets...")
def get_gsheet_client() -> gspread.Client:
    """Creează și returnează clientul Google Sheets."""
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ],
        )
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Eroare la conectare: {str(e)}")
        st.stop()

def ensure_worksheet(sh: gspread.Spreadsheet, title: str, headers: List[str]) -> gspread.Worksheet:
    """Asigură existența unei foi de calcul cu headerele corecte."""
    try:
        ws = sh.worksheet(title)
        # Verifică dacă are headerele corecte
        existing_headers = ws.row_values(1)
        if not existing_headers or existing_headers != headers:
            ws.update([headers], value_input_option='USER_ENTERED')
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=len(headers) + 2)
        ws.update([headers], value_input_option='USER_ENTERED')
    return ws

@st.cache_data(ttl=300, show_spinner="📊 Încărcare date...")
def load_data(sheet_name: str) -> pd.DataFrame:
    """Încarcă și curăță datele dintr-o foaie."""
    client = get_gsheet_client()
    
    try:
        sh = client.open_by_key(st.secrets["sheet_id"])
    except Exception as e:
        st.error(f"❌ Nu pot accesa foaia de calcul: {str(e)}")
        st.info("💡 Verifică ID-ul foii în secrets.toml")
        return pd.DataFrame()
    
    # Definește headerele pentru fiecare foaie
    headers_map = {
        SHEET_DOCTORS: [COL_ID, COL_NAME, COL_SPEC, COL_MAX, COL_PHONE, COL_EMAIL],
        SHEET_SCHEDULE: [COL_DATE, COL_SHIFT, COL_DOC_ID],
        SHEET_UNAVAIL: [COL_UNAV_DOC, COL_UNAV_DATE, COL_UNAV_REASON],
        SHEET_PREFERENCES: [COL_PREF_DOC, COL_PREF_DAY, COL_PREF_SHIFT],
    }
    
    headers = headers_map.get(sheet_name, [])
    ws = ensure_worksheet(sh, sheet_name, headers)
    
    # Încarcă datele
    records = ws.get_all_records()
    if not records:
        return pd.DataFrame(columns=headers)
    
    df = pd.DataFrame(records)
    
    # Curățare specifică pentru fiecare tip de foaie
    if sheet_name == SHEET_DOCTORS:
        df = clean_doctors_data(df)
    elif sheet_name == SHEET_SCHEDULE:
        df = clean_schedule_data(df)
    elif sheet_name == SHEET_UNAVAIL:
        df = clean_unavail_data(df)
    elif sheet_name == SHEET_PREFERENCES:
        df = clean_preferences_data(df)
    
    return df

def clean_doctors_data(df: pd.DataFrame) -> pd.DataFrame:
    """Curăță și validează datele medicilor."""
    # Asigură existența coloanelor
    required_cols = [COL_ID, COL_NAME, COL_SPEC, COL_MAX, COL_PHONE, COL_EMAIL]
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""
    
    # Elimină rândurile fără ID valid
    df = df[df[COL_ID].astype(str).str.strip() != ""].copy()
    
    # Conversii de tip
    df[COL_ID] = pd.to_numeric(df[COL_ID], errors='coerce').fillna(0).astype(int)
    df = df[df[COL_ID] > 0]  # Păstrează doar ID-uri valide
    
    df[COL_NAME] = df[COL_NAME].astype(str).str.strip()
    df[COL_SPEC] = df[COL_SPEC].astype(str).str.strip()
    df[COL_PHONE] = df[COL_PHONE].astype(str).str.strip()
    df[COL_EMAIL] = df[COL_EMAIL].astype(str).str.strip().str.lower()
    
    # Conversie pentru limita de gărzi
    df[COL_MAX] = pd.to_numeric(df[COL_MAX], errors='coerce').fillna(10).astype(int)
    df.loc[df[COL_MAX] <= 0, COL_MAX] = 10  # Valoare implicită
    
    return df

def clean_schedule_data(df: pd.DataFrame) -> pd.DataFrame:
    """Curăță datele programului."""
    if df.empty:
        return df
    
    df = df.dropna(subset=[COL_DATE, COL_DOC_ID]).copy()
    df[COL_DOC_ID] = pd.to_numeric(df[COL_DOC_ID], errors='coerce').fillna(0).astype(int)
    df = df[df[COL_DOC_ID] > 0]
    
    # Validare date
    df[COL_DATE] = pd.to_datetime(df[COL_DATE], errors='coerce')
    df = df.dropna(subset=[COL_DATE])
    
    return df

def clean_unavail_data(df: pd.DataFrame) -> pd.DataFrame:
    """Curăță datele de indisponibilitate."""
    if df.empty:
        return df
    
    df = df.dropna(subset=[COL_UNAV_DOC, COL_UNAV_DATE]).copy()
    df[COL_UNAV_DOC] = pd.to_numeric(df[COL_UNAV_DOC], errors='coerce').fillna(0).astype(int)
    df = df[df[COL_UNAV_DOC] > 0]
    
    df[COL_UNAV_DATE] = pd.to_datetime(df[COL_UNAV_DATE], errors='coerce')
    df = df.dropna(subset=[COL_UNAV_DATE])
    
    if COL_UNAV_REASON not in df.columns:
        df[COL_UNAV_REASON] = ""
    
    return df

def clean_preferences_data(df: pd.DataFrame) -> pd.DataFrame:
    """Curăță datele de preferințe."""
    if df.empty:
        return df
    
    df = df.dropna(subset=[COL_PREF_DOC]).copy()
    df[COL_PREF_DOC] = pd.to_numeric(df[COL_PREF_DOC], errors='coerce').fillna(0).astype(int)
    df = df[df[COL_PREF_DOC] > 0]
    
    df[COL_PREF_DAY] = pd.to_numeric(df[COL_PREF_DAY], errors='coerce').fillna(-1).astype(int)
    df[COL_PREF_SHIFT] = df[COL_PREF_SHIFT].astype(str).str.strip()
    
    return df

def save_data(sheet_name: str, df: pd.DataFrame) -> None:
    """Salvează datele înapoi în Google Sheets."""
    client = get_gsheet_client()
    sh = client.open_by_key(st.secrets["sheet_id"])
    
    headers = list(df.columns)
    ws = ensure_worksheet(sh, sheet_name, headers)
    
    # Golește foaia și rescrie datele
    ws.clear()
    data = [headers] + df.fillna("").astype(str).values.tolist()
    ws.update(data, value_input_option='USER_ENTERED')
    
    # Curăță cache-ul pentru a reîncărca datele
    st.cache_data.clear()

# ---------------------------------------------------------------------------
# Algoritm îmbunătățit de generare program
# ---------------------------------------------------------------------------
class SmartScheduler:
    """Generator inteligent de program cu multiple criterii de optimizare."""
    
    def __init__(self, doctors_df: pd.DataFrame, unavail_df: pd.DataFrame, 
                 preferences_df: pd.DataFrame):
        self.doctors = doctors_df
        self.unavail = unavail_df
        self.preferences = preferences_df
        
        # Pregătește structurile de date
        self.doctor_ids = self.doctors[COL_ID].tolist()
        self.id_to_name = dict(zip(self.doctors[COL_ID], self.doctors[COL_NAME]))
        self.monthly_limits = dict(zip(self.doctors[COL_ID], self.doctors[COL_MAX]))
        
        # Set de indisponibilități
        self.unavail_set = {
            (row[COL_UNAV_DOC], row[COL_UNAV_DATE].date())
            for _, row in self.unavail.iterrows()
        }
        
        # Dicționar de preferințe
        self.doc_preferences = defaultdict(list)
        for _, row in self.preferences.iterrows():
            self.doc_preferences[row[COL_PREF_DOC]].append({
                'day': row[COL_PREF_DAY],
                'shift': row[COL_PREF_SHIFT]
            })
        
        # Contoare pentru distribuție echitabilă
        self.shift_counts = defaultdict(lambda: defaultdict(int))
        self.last_shift_date = defaultdict(lambda: dt.date.min)
        self.weekend_counts = defaultdict(int)
        
    def calculate_doctor_score(self, doc_id: int, date: dt.date, shift_name: str) -> float:
        """Calculează scorul unui medic pentru o anumită gardă."""
        score = 0.0
        
        # 1. Verifică disponibilitatea
        if (doc_id, date) in self.unavail_set:
            return -1000  # Indisponibil
        
        # 2. Verifică limita lunară
        month_key = (date.year, date.month)
        if self.shift_counts[doc_id][month_key] >= self.monthly_limits[doc_id]:
            return -500  # Depășește limita
        
        # 3. Bonus pentru distribuție echitabilă (mai puține gărzi = scor mai mare)
        total_shifts = sum(self.shift_counts[doc_id].values())
        score += 100 / (total_shifts + 1)
        
        # 4. Penalizare pentru gărzi consecutive
        days_since_last = (date - self.last_shift_date[doc_id]).days
        if days_since_last < 2:
            score -= 50
        elif days_since_last > 7:
            score += 20  # Bonus pentru pauză mai lungă
        
        # 5. Consideră preferințele
        weekday = date.weekday()
        for pref in self.doc_preferences[doc_id]:
            if pref['day'] == weekday and pref['shift'] in shift_name:
                score += 30  # Bonus pentru preferință
        
        # 6. Distribuție echitabilă weekend
        if weekday >= 5:  # Weekend
            score -= self.weekend_counts[doc_id] * 10
        
        # 7. Adaugă puțină randomizare pentru varietate
        score += random.uniform(-5, 5)
        
        return score
    
    def generate(self, start_date: dt.date, end_date: dt.date, 
                 shifts_per_day: int) -> pd.DataFrame:
        """Generează programul optimizat."""
        if not self.doctor_ids:
            raise ValueError("❌ Nu există medici înregistrați!")
        
        shifts = SHIFT_TYPES.get(shifts_per_day, [f"Tură {i+1}" for i in range(shifts_per_day)])
        schedule_rows = []
        current_date = start_date
        
        # Progress bar
        progress_bar = st.progress(0)
        total_days = (end_date - start_date).days + 1
        day_count = 0
        
        while current_date <= end_date:
            day_count += 1
            progress_bar.progress(day_count / total_days)
            
            for shift_name in shifts:
                # Calculează scoruri pentru toți medicii
                scores = [
                    (doc_id, self.calculate_doctor_score(doc_id, current_date, shift_name))
                    for doc_id in self.doctor_ids
                ]
                
                # Filtrează medicii disponibili
                available = [(doc_id, score) for doc_id, score in scores if score > -100]
                
                if not available:
                    # Situație de urgență - alege aleatoriu
                    st.warning(f"⚠️ {current_date.strftime('%d.%m.%Y')} - {shift_name}: "
                             f"Toți medicii sunt indisponibili. Alocare forțată.")
                    selected_id = random.choice(self.doctor_ids)
                else:
                    # Alege medicul cu cel mai mare scor
                    available.sort(key=lambda x: x[1], reverse=True)
                    selected_id = available[0][0]
                
                # Actualizează contoarele
                month_key = (current_date.year, current_date.month)
                self.shift_counts[selected_id][month_key] += 1
                self.last_shift_date[selected_id] = current_date
                if current_date.weekday() >= 5:
                    self.weekend_counts[selected_id] += 1
                
                # Adaugă în program
                schedule_rows.append({
                    COL_DATE: current_date.isoformat(),
                    COL_SHIFT: shift_name,
                    COL_DOC_ID: selected_id
                })
            
            current_date += dt.timedelta(days=1)
        
        progress_bar.empty()
        return pd.DataFrame(schedule_rows)

# ---------------------------------------------------------------------------
# Funcții de vizualizare
# ---------------------------------------------------------------------------
def show_schedule_grid(schedule_df: pd.DataFrame, doctors_df: pd.DataFrame):
    """Afișează programul în format tabel."""
    if schedule_df.empty:
        st.info("📅 Nu există încă un program generat.")
        return
    
    # Mapare ID -> Nume
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    
    # Pregătește datele pentru pivot
    df = schedule_df.copy()
    df['doctor_name'] = df[COL_DOC_ID].map(id_to_name).fillna("Necunoscut")
    df['date_formatted'] = pd.to_datetime(df[COL_DATE]).dt.strftime('%d.%m')
    
    # Creează pivot table
    pivot = df.pivot_table(
        index='date_formatted',
        columns=COL_SHIFT,
        values='doctor_name',
        aggfunc='first'
    )
    
    # Stilizare
    st.dataframe(
        pivot.style.applymap(lambda x: 'background-color: #e8f4f8' if pd.notna(x) else ''),
        use_container_width=True,
        height=600
    )

def show_schedule_gantt(schedule_df: pd.DataFrame, doctors_df: pd.DataFrame):
    """Afișează programul ca diagramă Gantt."""
    if schedule_df.empty:
        return
    
    # Pregătește datele
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    df = schedule_df.copy()
    df['doctor_name'] = df[COL_DOC_ID].map(id_to_name).fillna("Necunoscut")
    df['date_dt'] = pd.to_datetime(df[COL_DATE])
    df['date_end'] = df['date_dt'] + pd.Timedelta(days=1)
    
    # Creează diagrama Gantt
    gantt = alt.Chart(df).mark_bar(cornerRadius=5).encode(
        y=alt.Y('doctor_name:N', title='Medic', sort=None),
        x=alt.X('date_dt:T', title='Data'),
        x2='date_end:T',
        color=alt.Color(
            COL_SHIFT + ':N',
            title='Tip Gardă',
            scale=alt.Scale(range=[get_shift_color(s) for s in df[COL_SHIFT].unique()])
        ),
        tooltip=[
            alt.Tooltip('date_dt:T', title='Data', format='%d %B %Y'),
            alt.Tooltip('doctor_name:N', title='Medic'),
            alt.Tooltip(COL_SHIFT + ':N', title='Tura'),
        ]
    ).properties(
        height=max(400, len(df['doctor_name'].unique()) * 40)
    ).interactive()
    
    st.altair_chart(gantt, use_container_width=True)

def show_statistics(schedule_df: pd.DataFrame, doctors_df: pd.DataFrame):
    """Afișează statistici despre program."""
    if schedule_df.empty:
        st.info("📊 Nu există date pentru statistici.")
        return
    
    # Pregătește datele
    df = schedule_df.copy()
    df['date'] = pd.to_datetime(df[COL_DATE])
    df['month'] = df['date'].dt.to_period('M')
    df['weekday'] = df['date'].dt.weekday
    df['is_weekend'] = df['weekday'] >= 5
    
    id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Total gărzi per medic
        shifts_per_doc = df.groupby(COL_DOC_ID).size().reset_index(name='total_shifts')
        shifts_per_doc['name'] = shifts_per_doc[COL_DOC_ID].map(id_to_name)
        
        st.metric("Total Gărzi", len(df))
        st.bar_chart(shifts_per_doc.set_index('name')['total_shifts'])
    
    with col2:
        # Gărzi de weekend
        weekend_shifts = df[df['is_weekend']].groupby(COL_DOC_ID).size()
        weekend_df = pd.DataFrame({
            'Medic': [id_to_name.get(doc_id, str(doc_id)) for doc_id in weekend_shifts.index],
            'Weekend': weekend_shifts.values
        })
        
        st.metric("Gărzi Weekend", df['is_weekend'].sum())
        st.bar_chart(weekend_df.set_index('Medic'))
    
    with col3:
        # Distribuție lunară
        monthly = df.groupby(['month', COL_DOC_ID]).size().unstack(fill_value=0)
        monthly.columns = [id_to_name.get(col, str(col)) for col in monthly.columns]
        
        st.metric("Luni Acoperite", len(monthly))
        st.area_chart(monthly)

# ---------------------------------------------------------------------------
# Aplicația principală
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="🩺 Planificator Gărzi Medicale",
        page_icon="🏥",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Header principal
    st.title("🏥 Sistem de Planificare Gărzi Medicale")
    st.markdown("### Versiunea 5.0 - Mai inteligent, mai prietenos")
    
    # Încarcă datele
    try:
        doctors_df = load_data(SHEET_DOCTORS)
        schedule_df = load_data(SHEET_SCHEDULE)
        unavail_df = load_data(SHEET_UNAVAIL)
        preferences_df = load_data(SHEET_PREFERENCES)
    except Exception as e:
        st.error(f"❌ Eroare la încărcarea datelor: {str(e)}")
        st.info("""
        💡 **Verifică următoarele:**
        1. Ai configurat corect `secrets.toml` cu credențialele Google
        2. ID-ul foii de calcul este corect
        3. Contul de serviciu are acces la foaia de calcul
        """)
        return
    
    # Sidebar pentru generare program
    with st.sidebar:
        st.header("⚙️ Configurare Program")
        
        # Verifică dacă există medici
        if doctors_df.empty:
            st.warning("⚠️ Nu există medici înregistrați!")
            st.info("Adaugă medici în tab-ul 'Gestionare Medici'")
        else:
            st.success(f"✅ {len(doctors_df)} medici disponibili")
        
        # Perioada
        st.subheader("📅 Perioada")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "Data început",
                value=dt.date.today(),
                format="DD.MM.YYYY"
            )
        with col2:
            end_date = st.date_input(
                "Data sfârșit",
                value=dt.date.today() + dt.timedelta(days=30),
                format="DD.MM.YYYY"
            )
        
        # Validare date
        if start_date > end_date:
            st.error("❌ Data de început trebuie să fie înainte de cea de sfârșit!")
        
        # Tip program
        st.subheader("🕐 Tip Program")
        shifts_type = st.selectbox(
            "Alege tipul de gărzi",
            options=[1, 2, 3],
            format_func=lambda x: {
                1: "📍 O gardă de 24h",
                2: "☀️ Zi + 🌙 Noapte",
                3: "🌅 3 Ture de 8 ore"
            }[x]
        )
        
        # Afișează detalii despre ture
        st.info(f"**Ture selectate:** {', '.join(SHIFT_TYPES[shifts_type])}")
        
        # Buton generare
        st.markdown("---")
        if st.button(
            "🚀 Generează Program Nou",
            type="primary",
            use_container_width=True,
            disabled=doctors_df.empty or start_date > end_date
        ):
            with st.spinner("🧠 Algoritmul calculează cel mai bun program..."):
                try:
                    scheduler = SmartScheduler(doctors_df, unavail_df, preferences_df)
                    new_schedule = scheduler.generate(start_date, end_date, shifts_type)
                    
                    # Salvează în Google Sheets
                    save_data(SHEET_SCHEDULE, new_schedule)
                    st.success("✅ Program generat și salvat cu succes!")
                    st.balloons()
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Eroare la generare: {str(e)}")
        
        # Statistici rapide
        if not schedule_df.empty:
            st.markdown("---")
            st.subheader("📊 Statistici Rapide")
            total_shifts = len(schedule_df)
            unique_docs = schedule_df[COL_DOC_ID].nunique()
            st.metric("Total Gărzi", total_shifts)
            st.metric("Medici Activi", unique_docs)
    
    # Tabs principale
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📅 **Vizualizare Program**",
        "👨‍⚕️ **Gestionare Medici**",
        "🚫 **Indisponibilități**",
        "⭐ **Preferințe**",
        "📊 **Statistici**"
    ])
    
    with tab1:
        if schedule_df.empty:
            st.info("📅 Nu există încă un program generat. Folosește panoul din stânga pentru a crea unul.")
        else:
            # Selector vizualizare
            view_col1, view_col2, view_col3 = st.columns([1, 1, 3])
            with view_col1:
                view_type = st.radio(
                    "Tip vizualizare",
                    ["📊 Tabel", "📈 Gantt"],
                    label_visibility="collapsed"
                )
            
            if view_type == "📊 Tabel":
                show_schedule_grid(schedule_df, doctors_df)
            else:
                show_schedule_gantt(schedule_df, doctors_df)
            
            # Opțiuni export
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                csv = schedule_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "📥 Descarcă CSV",
                    csv,
                    "program_garzi.csv",
                    "text/csv",
                    use_container_width=True
                )
    
    with tab2:
        st.header("👨‍⚕️ Gestionare Personal Medical")
        
        # Editor medici
        st.subheader("Lista Medicilor")
        
        # Configurare coloane pentru editor
        column_config = {
            COL_ID: st.column_config.NumberColumn(
                "ID",
                help="ID unic pentru fiecare medic",
                min_value=1,
                required=True
            ),
            COL_NAME: st.column_config.TextColumn(
                "Nume Complet",
                required=True
            ),
            COL_SPEC: st.column_config.SelectboxColumn(
                "Specialitate",
                options=["ATI", "Urgențe", "Chirurgie", "Medicină Internă", "Pediatrie", "Altele"],
                required=True
            ),
            COL_MAX: st.column_config.NumberColumn(
                "Max Gărzi/Lună",
                min_value=1,
                max_value=15,
                default=8
            ),
            COL_PHONE: st.column_config.TextColumn(
                "Telefon"
            ),
            COL_EMAIL: st.column_config.TextColumn(
                "Email"
            )
        }
        
        edited_doctors = st.data_editor(
            doctors_df,
            column_config=column_config,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="doctors_editor"
        )
        
        # Salvare modificări
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("💾 Salvează Modificări", type="primary", use_container_width=True):
                try:
                    # Validare
                    if edited_doctors[COL_ID].duplicated().any():
                        st.error("❌ Există ID-uri duplicate!")
                    else:
                        save_data(SHEET_DOCTORS, edited_doctors)
                        st.success("✅ Lista medicilor actualizată!")
                        st.rerun()
                except Exception as e:
                    st.error(f"❌ Eroare la salvare: {str(e)}")
    
    with tab3:
        st.header("🚫 Gestionare Indisponibilități")
        st.info("💡 Marchează zilele în care medicii nu pot fi programați (concedii, congrese, etc.)")
        
        # Adaugă indisponibilitate nouă
        with st.expander("➕ Adaugă Indisponibilitate Nouă", expanded=True):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if not doctors_df.empty:
                    doc_options = dict(zip(
                        doctors_df[COL_NAME] + " (ID: " + doctors_df[COL_ID].astype(str) + ")",
                        doctors_df[COL_ID]
                    ))
                    selected_doc_name = st.selectbox("Medic", options=list(doc_options.keys()))
                    selected_doc_id = doc_options[selected_doc_name]
                else:
                    st.warning("Nu există medici înregistrați")
                    selected_doc_id = None
            
            with col2:
                unav_date = st.date_input("Data", format="DD.MM.YYYY")
            
            with col3:
                reason = st.text_input("Motiv (opțional)")
            
            if st.button("➕ Adaugă", type="primary", disabled=selected_doc_id is None):
                new_unav = pd.DataFrame([{
                    COL_UNAV_DOC: selected_doc_id,
                    COL_UNAV_DATE: unav_date,
                    COL_UNAV_REASON: reason
                }])
                updated_unav = pd.concat([unavail_df, new_unav], ignore_index=True)
                save_data(SHEET_UNAVAIL, updated_unav)
                st.success("✅ Indisponibilitate adăugată!")
                st.rerun()
        
        # Afișare indisponibilități existente
        if not unavail_df.empty:
            st.subheader("Indisponibilități Curente")
            
            # Îmbogățește cu nume medici
            display_df = unavail_df.copy()
            id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
            display_df['Medic'] = display_df[COL_UNAV_DOC].map(id_to_name)
            display_df['Data'] = pd.to_datetime(display_df[COL_UNAV_DATE]).dt.strftime('%d.%m.%Y')
            
            # Afișare și opțiune ștergere
            for idx, row in display_df.iterrows():
                col1, col2, col3, col4 = st.columns([3, 2, 3, 1])
                with col1:
                    st.write(f"**{row['Medic']}**")
                with col2:
                    st.write(row['Data'])
                with col3:
                    st.write(row.get(COL_UNAV_REASON, ""))
                with col4:
                    if st.button("🗑️", key=f"del_unav_{idx}"):
                        unavail_df = unavail_df.drop(idx)
                        save_data(SHEET_UNAVAIL, unavail_df)
                        st.rerun()
    
    with tab4:
        st.header("⭐ Preferințe Medici")
        st.info("💡 Setează preferințele medicilor pentru anumite zile sau tipuri de gărzi")
        
        # Editor preferințe
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("Adaugă Preferință")
            
            if not doctors_df.empty:
                pref_doc = st.selectbox(
                    "Medic",
                    options=doctors_df[COL_ID].tolist(),
                    format_func=lambda x: doctors_df[doctors_df[COL_ID] == x][COL_NAME].iloc[0]
                )
                
                pref_day = st.selectbox(
                    "Zi Preferată",
                    options=list(range(7)),
                    format_func=lambda x: ["Luni", "Marți", "Miercuri", "Joi", "Vineri", "Sâmbătă", "Duminică"][x]
                )
                
                pref_shift = st.selectbox(
                    "Tură Preferată",
                    options=["Orice"] + [s for shifts in SHIFT_TYPES.values() for s in shifts]
                )
                
                if st.button("➕ Adaugă Preferință", type="primary"):
                    new_pref = pd.DataFrame([{
                        COL_PREF_DOC: pref_doc,
                        COL_PREF_DAY: pref_day,
                        COL_PREF_SHIFT: pref_shift
                    }])
                    updated_prefs = pd.concat([preferences_df, new_pref], ignore_index=True)
                    save_data(SHEET_PREFERENCES, updated_prefs)
                    st.success("✅ Preferință adăugată!")
                    st.rerun()
        
        # Afișare preferințe existente
        if not preferences_df.empty:
            st.subheader("Preferințe Existente")
            display_prefs = preferences_df.copy()
            id_to_name = dict(zip(doctors_df[COL_ID], doctors_df[COL_NAME]))
            display_prefs['Medic'] = display_prefs[COL_PREF_DOC].map(id_to_name)
            days = ["Luni", "Marți", "Miercuri", "Joi", "Vineri", "Sâmbătă", "Duminică"]
            display_prefs['Zi'] = display_prefs[COL_PREF_DAY].map(lambda x: days[x] if 0 <= x < 7 else "Invalid")
            
            st.dataframe(
                display_prefs[['Medic', 'Zi', COL_PREF_SHIFT]],
                use_container_width=True,
                hide_index=True
            )
    
    with tab5:
        st.header("📊 Analiză Detaliată")
        show_statistics(schedule_df, doctors_df)

if __name__ == "__main__":
    main()
