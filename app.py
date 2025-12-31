import streamlit as st
import sqlite3
import os
import numpy as np
import json
import pandas as pd
from groq import Groq
from dotenv import load_dotenv
from datetime import datetime, date, time

# --- CONFIGURATION ---
load_dotenv()
st.set_page_config(page_title="Senior Care Agent", page_icon="🛡️", layout="wide")

if not os.getenv("GROQ_API_KEY"):
    st.error("⚠️ GROQ_API_KEY not found in .env file")
    st.stop()

# FORCE USE OF LLAMA 3.3 70B
MODEL_NAME = "llama-3.3-70b-versatile"
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
DB_FILE = "care_data.db"

# --- SOUND ASSET (Simple Beep Alarm) ---
ALARM_SOUND_B64 = "data:audio/mp3;base64,//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uQxAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"

# --- DATABASE MANAGEMENT ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Logs Table
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        author TEXT,
        original_text TEXT,
        category TEXT,
        severity TEXT
    )''')
    for col in ["severity", "category", "author"]:
        try: c.execute(f"ALTER TABLE logs ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError: pass

    # 2. Meds Table
    c.execute('''CREATE TABLE IF NOT EXISTS medications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        dosage TEXT,
        time TEXT,
        purpose TEXT
    )''')
    try: c.execute("ALTER TABLE medications ADD COLUMN time TEXT")
    except sqlite3.OperationalError: pass 

    # 3. Appointments Table
    c.execute('''CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        doctor TEXT,
        purpose TEXT
    )''')

    # 4. DAILY ROUTINE TABLE
    c.execute('''CREATE TABLE IF NOT EXISTS routines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        task TEXT,
        scheduled_time TEXT,
        completed BOOLEAN
    )''')
    
    # 5. PATIENT PROFILE TABLE (NEW)
    c.execute('''CREATE TABLE IF NOT EXISTS patient_profile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        age TEXT,
        conditions TEXT
    )''')
    
    # Init profile if empty
    c.execute("SELECT count(*) FROM patient_profile")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO patient_profile (age, conditions) VALUES (?, ?)", ("75", "Hypertension, Arthritis"))

    conn.commit()
    conn.close()

# --- HELPER: INITIALIZE DAILY TASKS ---
def check_and_create_daily_tasks():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today_str = date.today().strftime("%Y-%m-%d")
    c.execute("SELECT count(*) FROM routines WHERE date = ?", (today_str,))
    count = c.fetchone()[0]
    
    if count == 0:
        defaults = [
            ("Breakfast", "08:00"),
            ("Morning Meds", "09:00"),
            ("Lunch", "13:00"),
            ("Afternoon Walk", "17:00"),
            ("Dinner", "20:00"),
            ("Night Meds", "21:00")
        ]
        for task, t_time in defaults:
            c.execute("INSERT INTO routines (date, task, scheduled_time, completed) VALUES (?, ?, ?, ?)", 
                      (today_str, task, t_time, False))
        conn.commit()
    conn.close()

# --- HELPER: INJECT ALARM SCRIPT ---
def inject_alarm_logic(tasks_df):
    pending = tasks_df[tasks_df['completed'] == 0]
    alarm_data = dict(zip(pending['scheduled_time'], pending['task']))
    alarm_json = json.dumps(alarm_data)
    
    js_code = f"""
        <audio id="alarm_audio" src="{ALARM_SOUND_B64}" preload="auto"></audio>
        <script>
            var alarms = {alarm_json};
            setInterval(function() {{
                var now = new Date();
                var hours = String(now.getHours()).padStart(2, '0');
                var minutes = String(now.getMinutes()).padStart(2, '0');
                var currentTime = hours + ":" + minutes;
                if (currentTime in alarms) {{
                    var taskName = alarms[currentTime];
                    var audio = document.getElementById("alarm_audio");
                    audio.play().catch(error => console.log("Autoplay blocked:", error));
                    alert("⏰ ALARM: Time for " + taskName + "!");
                }}
            }}, 10000);
        </script>
    """
    st.components.v1.html(js_code, height=0)

# --- AI FUNCTIONS (ALL USE LLAMA 3.3) ---
def ask_ai(prompt, json_mode=True):
    try:
        kwargs = {
            "messages": [{"role": "system", "content": "You are a senior care medical expert."}, 
                         {"role": "user", "content": prompt}],
            "model": MODEL_NAME, 
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        completion = client.chat.completions.create(**kwargs)
        return json.loads(completion.choices[0].message.content) if json_mode else completion.choices[0].message.content
    except Exception as e:
        return {"error": str(e)}

def analyze_medical_text(report_text):
    prompt = f"""
    You are a helpful medical assistant for a family. 
    Here is the text from a medical report/lab result: "{report_text}"
    1. Identify the key test names and values.
    2. Translate what they mean into plain English for a non-doctor.
    3. If values seem high/low based on general knowledge, mention it gently.
    Return the response in clear Markdown format.
    """
    return ask_ai(prompt, json_mode=False)

def check_drug_interactions(meds_list):
    prompt = f"""Analyze this list of medications for dangerous interactions: {meds_list}. Return JSON: "safe": bool, "warnings": list, "recommendation": str"""
    return ask_ai(prompt)

def check_food_interaction(food_item, meds_list):
    prompt = f"""Patient's Meds: {meds_list}. Food: "{food_item}". Analyze Food-Drug interactions. Return JSON: "safe": bool, "warning": str, "advice": str"""
    return ask_ai(prompt)

def detect_patterns(history_text):
    prompt = f"""Analyze logs for "Slow Declines". Return JSON: "concern_detected": bool, "pattern_description": str, "advice": str. Logs: {history_text}"""
    return ask_ai(prompt)

def generate_newsletter(history_text):
    prompt = f"""Summarize these logs: {history_text}. Organize by "Physical Health", "Mood", "Upcoming Needs". Direct message format. No "Dear Family"."""
    return ask_ai(prompt, json_mode=False)

def check_symptoms_with_context(symptoms, age, conditions, meds):
    prompt = f"""
    Act as a professional medical triage nurse (Dr. AI).
    
    PATIENT PROFILE:
    - Age: {age}
    - Known Conditions: {conditions}
    - Current Medications: {meds}
    
    NEW SYMPTOMS:
    "{symptoms}"
    
    Analyze the symptoms specifically in the context of their age, conditions, and meds.
    
    Return JSON with:
    - "triage_level": (String: "Emergency - Call 911", "Urgent - See Doctor 24h", "Non-Urgent - Monitor")
    - "analysis": (String: Explain WHY, linking symptoms to conditions/meds if relevant)
    - "action_plan": (String: Bullet points of what to do right now)
    - "disclaimer": (String: Strict medical disclaimer)
    """
    return ask_ai(prompt)

# --- UI LOGIC ---
init_db()
check_and_create_daily_tasks()

# 1. FETCH TASKS & INJECT ALARM
conn = sqlite3.connect(DB_FILE)
today_str = date.today().strftime("%Y-%m-%d")
tasks_df = pd.read_sql_query(f"SELECT id, task, scheduled_time, completed FROM routines WHERE date = '{today_str}'", conn)
conn.close()
inject_alarm_logic(tasks_df)

# Sidebar
st.sidebar.title("🛡️ Care Agent")
page = st.sidebar.radio("Go to:", ["Dashboard", "Daily Routine", "Medication Safety", "Shared Calendar", "Family Updates", "Medical Reports", "Dr. AI Symptom Checker"])

# === PAGE 1: DASHBOARD ===
if page == "Dashboard":
    st.header("🏠 Care Team Dashboard")
    
    current_hour = datetime.now().hour
    overdue_alerts = []
    for _, row in tasks_df[tasks_df['completed']==0].iterrows():
        task_hour = int(row['scheduled_time'].split(":")[0])
        if current_hour > (task_hour + 1):
            overdue_alerts.append(f"⚠️ MISSED: **{row['task']}** (Scheduled: {row['scheduled_time']})")
    
    if overdue_alerts:
        st.warning("🔔 **ACTIVE REMINDERS**")
        for alert in overdue_alerts: st.write(alert)
    
    conn = sqlite3.connect(DB_FILE)
    recent_high_risk = pd.read_sql_query("SELECT * FROM logs WHERE severity = 'High' ORDER BY id DESC LIMIT 1", conn)
    conn.close()
    if not recent_high_risk.empty:
        st.error(f"🚨 ALERT: {recent_high_risk.iloc[0]['original_text']} ({recent_high_risk.iloc[0]['timestamp']})")

    with st.container(border=True):
        st.subheader("📝 New Log Entry")
        c1, c2 = st.columns([1, 3])
        author = c1.selectbox("Who are you?", ["Daughter", "Son", "Nurse", "Caregiver"])
        log_text = c2.text_area("What happened?", placeholder="Ex: Mom fell in the hallway but says she is okay.")
        
        if st.button("Submit Log", type="primary"):
            analysis = ask_ai(f"Analyze: '{log_text}'. Return JSON: category (Vitals/Activity/Mood/Incident), severity (Low/Medium/High).")
            conn = sqlite3.connect(DB_FILE)
            conn.execute("INSERT INTO logs (author, original_text, category, severity) VALUES (?, ?, ?, ?)", 
                         (author, log_text, analysis.get('category', 'General'), analysis.get('severity', 'Low')))
            conn.commit()
            conn.close()
            st.rerun()

    st.subheader("📜 Recent Activity")
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT id, timestamp, author, category, severity, original_text FROM logs ORDER BY id DESC LIMIT 10", conn)
    conn.close()
    if not df.empty:
        for index, row in df.iterrows():
            with st.container(border=True):
                c_main, c_del = st.columns([8, 1])
                with c_main:
                    icon = "🔴" if row['severity'] == "High" else "🟢"
                    st.markdown(f"**{row['author']}** ({row['timestamp']}) {icon}")
                    st.write(row['original_text'])
                    st.caption(f"Category: {row['category']}")
                with c_del:
                    if st.button("🗑️", key=f"del_log_{row['id']}"):
                        conn = sqlite3.connect(DB_FILE)
                        conn.execute("DELETE FROM logs WHERE id = ?", (row['id'],))
                        conn.commit()
                        conn.close()
                        st.rerun()

# === PAGE 2: DAILY ROUTINE ===
elif page == "Daily Routine":
    st.header("✅ Daily Routine Tracker")
    st.caption(f"Tasks for {date.today().strftime('%B %d, %Y')}")
    
    with st.expander("⚙️ Configure Schedule (Add/Edit Times)"):
        st.write("Add new tasks or edit timings for today.")
        c_new_1, c_new_2, c_new_3 = st.columns([3, 2, 2])
        new_task_name = c_new_1.text_input("New Task Name", placeholder="e.g. Physiotherapy")
        new_task_time = c_new_2.time_input("Time", value=time(10, 0))
        if c_new_3.button("➕ Add Task"):
            if new_task_name:
                time_str = new_task_time.strftime("%H:%M")
                conn = sqlite3.connect(DB_FILE)
                conn.execute("INSERT INTO routines (date, task, scheduled_time, completed) VALUES (?, ?, ?, ?)", 
                             (today_str, new_task_name, time_str, False))
                conn.commit()
                conn.close()
                st.rerun()
        st.divider()
        st.write("Edit Existing Tasks:")
        for index, row in tasks_df.iterrows():
            c_edit_1, c_edit_2, c_edit_3 = st.columns([3, 2, 2])
            c_edit_1.text(row['task'])
            current_t_obj = datetime.strptime(row['scheduled_time'], "%H:%M").time()
            new_t_obj = c_edit_2.time_input("Set Time", value=current_t_obj, key=f"time_{row['id']}", label_visibility="collapsed")
            if c_edit_3.button("💾 Save", key=f"save_{row['id']}"):
                 new_time_str = new_t_obj.strftime("%H:%M")
                 conn = sqlite3.connect(DB_FILE)
                 conn.execute("UPDATE routines SET scheduled_time = ? WHERE id = ?", (new_time_str, row['id']))
                 conn.commit()
                 conn.close()
                 st.rerun()
            if c_edit_3.button("🗑️ Del", key=f"del_task_{row['id']}"):
                 conn = sqlite3.connect(DB_FILE)
                 conn.execute("DELETE FROM routines WHERE id = ?", (row['id'],))
                 conn.commit()
                 conn.close()
                 st.rerun()
                 
    st.divider()
    tasks_df = tasks_df.sort_values(by="scheduled_time")
    current_time = datetime.now().time()
    
    for index, row in tasks_df.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 4, 2])
            is_checked = c1.checkbox("", value=bool(row['completed']), key=f"check_{row['id']}")
            
            if is_checked != bool(row['completed']):
                conn = sqlite3.connect(DB_FILE)
                conn.execute("UPDATE routines SET completed = ? WHERE id = ?", (is_checked, row['id']))
                conn.commit()
                conn.close()
                st.rerun()
                
            task_time_obj = datetime.strptime(row['scheduled_time'], "%H:%M").time()
            if row['completed']:
                status_color, status_text = "green", "Done"
            elif current_time > task_time_obj:
                status_color, status_text = "red", "Overdue"
            else:
                status_color, status_text = "gray", "Upcoming"
            with c2: st.markdown(f"~~**{row['task']}**~~" if row['completed'] else f"**{row['task']}**")
            with c3: st.markdown(f":{status_color}[{row['scheduled_time']} ({status_text})]")

# === PAGE 3: MEDICATION SAFETY ===
elif page == "Medication Safety":
    st.header("💊 Medication Safety Net")
    conn = sqlite3.connect(DB_FILE)
    meds_df = pd.read_sql_query("SELECT id, name, dosage, time FROM medications", conn)
    conn.close()
    
    c1, c2 = st.columns(2)
    with c1:
        with st.form("add_med"):
            st.subheader("Add Prescription")
            name = st.text_input("Drug Name (e.g., Warfarin)")
            dosage = st.text_input("Dosage (e.g., 5mg)")
            time_val = st.text_input("Time (e.g., Morning / 8:00 AM)")
            if st.form_submit_button("Add to Cabinet"):
                conn = sqlite3.connect(DB_FILE)
                conn.execute("INSERT INTO medications (name, dosage, time) VALUES (?, ?, ?)", (name, dosage, time_val))
                conn.commit()
                conn.close()
                st.success(f"Added {name}")
                st.rerun()
    with c2:
        st.subheader("Current Cabinet")
        if not meds_df.empty:
            for index, row in meds_df.iterrows():
                with st.container(border=True):
                    col_name, col_dose, col_time, col_del = st.columns([2, 2, 2, 1])
                    col_name.write(f"**{row['name']}**")
                    col_dose.write(row['dosage'])
                    col_time.write(f"🕒 {row['time']}")
                    if col_del.button("🗑️", key=f"del_med_{row['id']}"):
                        conn = sqlite3.connect(DB_FILE)
                        conn.execute("DELETE FROM medications WHERE id = ?", (row['id'],))
                        conn.commit()
                        conn.close()
                        st.rerun()
            st.divider()
            if st.button("⚠️ Check Drug Interactions (AI)", type="primary"):
                with st.spinner("Checking..."):
                    med_list = meds_df['name'].tolist()
                    report = check_drug_interactions(str(med_list))
                    if report.get("safe"): st.success("✅ No dangerous interactions detected.")
                    else:
                        st.error("❌ INTERACTION WARNING")
                        for warn in report.get("warnings", []): st.write(f"- {warn}")
        else: st.info("Cabinet is empty.")

    st.markdown("---")
    st.subheader("🥗 Food Safety Checker")
    fc1, fc2 = st.columns([1, 2])
    with fc1:
        food_input = st.text_input("Enter Food/Drink", placeholder="e.g. Grapefruit Juice")
        if st.button("Check Safety", type="primary"):
            if not food_input: st.warning("Please enter a food item.")
            elif meds_df.empty: st.info("Cabinet is empty. Please add medicines first.")
            else:
                with st.spinner(f"Analyzing..."):
                    med_list_str = str(meds_df['name'].tolist())
                    result = check_food_interaction(food_input, med_list_str)
                    with fc2:
                        if result.get("safe"):
                            st.success(f"✅ **{food_input}** appears safe.")
                            if result.get("advice"): st.info(result["advice"])
                        else:
                            st.error(f"⚠️ **Caution Required**")
                            st.write(f"**Warning:** {result.get('warning')}")
                            st.write(f"**Advice:** {result.get('advice')}")

# === PAGE 4: SHARED CALENDAR ===
elif page == "Shared Calendar":
    st.header("📅 Shared Family Calendar")
    conn = sqlite3.connect(DB_FILE)
    appt_df = pd.read_sql_query("SELECT id, date, doctor, purpose FROM appointments ORDER BY date ASC", conn)
    conn.close()
    if not appt_df.empty:
        today = date.today()
        for _, row in appt_df.iterrows():
            try:
                appt_date = datetime.strptime(row['date'], '%Y-%m-%d').date()
                delta = (appt_date - today).days
                if delta == 0: st.warning(f"🔔 REMINDER: Appointment with **{row['doctor']}** is **TODAY**!")
                elif delta == 1: st.warning(f"🔔 REMINDER: Appointment with **{row['doctor']}** is **TOMORROW**!")
            except: pass
    c1, c2 = st.columns([1, 2])
    with c1:
        with st.form("appt_form"):
            st.subheader("New Appointment")
            date_val = st.date_input("Date")
            doc = st.text_input("Doctor/Location")
            purpose = st.text_input("Purpose")
            if st.form_submit_button("Schedule"):
                conn = sqlite3.connect(DB_FILE)
                conn.execute("INSERT INTO appointments (date, doctor, purpose) VALUES (?, ?, ?)", (date_val, doc, purpose))
                conn.commit()
                conn.close()
                st.rerun()
    with c2:
        st.subheader("Upcoming Appointments")
        if not appt_df.empty:
            for index, row in appt_df.iterrows():
                with st.container(border=True):
                    col_date, col_doc, col_purp, col_del = st.columns([2, 3, 3, 1])
                    col_date.write(f"📅 **{row['date']}**")
                    col_doc.write(row['doctor'])
                    col_purp.write(f"_{row['purpose']}_")
                    if col_del.button("🗑️", key=f"del_appt_{row['id']}"):
                        conn = sqlite3.connect(DB_FILE)
                        conn.execute("DELETE FROM appointments WHERE id = ?", (row['id'],))
                        conn.commit()
                        conn.close()
                        st.rerun()
        else: st.write("No upcoming appointments.")

# === PAGE 5: FAMILY UPDATES ===
elif page == "Family Updates":
    st.header("🧠 Smart Insights & Updates")
    conn = sqlite3.connect(DB_FILE)
    history_df = pd.read_sql_query("SELECT timestamp, original_text FROM logs ORDER BY id DESC LIMIT 20", conn)
    conn.close()
    history_text = history_df.to_string() if not history_df.empty else "No logs available."
    tab1, tab2 = st.tabs(["📉 Pattern Detection", "✉️ Family Summary"])
    with tab1:
        st.subheader("Detect Silent Declines")
        if st.button("Run Pattern Analysis"):
            with st.spinner("Analyzing..."):
                analysis = detect_patterns(history_text)
                if analysis.get("concern_detected"):
                    st.warning(f"⚠️ Pattern Detected: {analysis['pattern_description']}")
                    st.write(f"**Advice:** {analysis['advice']}")
                else: st.success("✅ Trends look stable.")
    with tab2:
        st.subheader("Generate Weekly Summary")
        if st.button("Generate Summary"):
            with st.spinner("Writing..."):
                email_body = generate_newsletter(history_text)
                st.text_area("Weekly Summary:", value=email_body, height=300)

# === PAGE 6: MEDICAL REPORTS (TEXT ONLY) ===
elif page == "Medical Reports":
    st.header("📄 Medical Report Decoder")
    st.caption("Paste the text from a lab report or email. AI will translate the jargon into plain English.")
    
    # Text Area input instead of Image Upload
    report_text = st.text_area("Paste Report Text Here:", height=200, placeholder="e.g. 'Creatinine: 1.4, BUN: 25, Potassium: 3.8...'")
    
    if st.button("🔍 Decode Report", type="primary"):
        if not report_text:
            st.warning("Please paste some text first.")
        else:
            with st.spinner("Decoding medical jargon..."):
                # Call Llama 3.3 Text Model
                analysis = analyze_medical_text(report_text)
                
                # Show Result
                st.subheader("📝 Plain English Translation")
                st.markdown(analysis)
                st.success("Analysis Complete!")

# === PAGE 7: DR. AI SYMPTOM CHECKER (NEW) ===
elif page == "Dr. AI Symptom Checker":
    st.header("🧠 Dr. AI: Symptom Triage")
    st.caption("Enter symptoms to get a triage assessment based on the patient's specific history and medications.")

    # 1. FETCH PROFILE & MEDS
    conn = sqlite3.connect(DB_FILE)
    profile = conn.execute("SELECT age, conditions FROM patient_profile").fetchone()
    meds_df = pd.read_sql_query("SELECT name FROM medications", conn)
    conn.close()
    
    age, conditions = profile
    meds_list_str = str(meds_df['name'].tolist()) if not meds_df.empty else "No medications listed"

    # 2. PROFILE CONFIGURATION (Expandable)
    with st.expander("👤 Patient Context (Review/Edit)"):
        c1, c2 = st.columns(2)
        new_age = c1.text_input("Patient Age", value=age)
        new_cond = c2.text_input("Existing Conditions", value=conditions)
        if st.button("Update Profile"):
            conn = sqlite3.connect(DB_FILE)
            conn.execute("UPDATE patient_profile SET age = ?, conditions = ? WHERE id = 1", (new_age, new_cond))
            conn.commit()
            conn.close()
            st.success("Profile Updated!")
            st.rerun()

    # 3. SYMPTOM INPUT
    st.markdown("---")
    symptoms = st.text_area(" Describe the Symptoms:", placeholder="e.g. Swollen ankles and shortness of breath since this morning.")
    
    if st.button("🚑 Check Symptoms", type="primary"):
        if not symptoms:
            st.warning("Please enter symptoms.")
        else:
            with st.spinner("Dr. AI is analyzing history, meds, and symptoms..."):
                result = check_symptoms_with_context(symptoms, age, conditions, meds_list_str)
                
                # 4. DISPLAY RESULTS
                triage = result.get("triage_level", "Unknown")
                
                # Color code the result
                if "Emergency" in triage:
                    st.error(f"🔴 **TRIAGE: {triage}**")
                elif "Urgent" in triage:
                    st.warning(f"🟠 **TRIAGE: {triage}**")
                else:
                    st.success(f"🟢 **TRIAGE: {triage}**")
                
                st.subheader("Analysis")
                st.write(result.get("analysis"))
                
                st.subheader("Recommended Action Plan")
                st.info(result.get("action_plan"))
                
                st.caption(f"⚠️ **DISCLAIMER:** {result.get('disclaimer')}")