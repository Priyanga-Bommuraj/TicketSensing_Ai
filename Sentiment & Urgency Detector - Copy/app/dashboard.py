# dashboard.py
import os
import re
import json
import sqlite3
import requests
import pandas as pd
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv

# Load environmental variables directly from your root file
load_dotenv()

# --- HARDENED ARCHITECTURE SETTINGS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DB_PATH = "ticketsense.db"

GROQ_MODEL_PRIMARY = "llama3-70b-8192"
GROQ_MODEL_FALLBACK = "llama3-8b-8192"

# --- LOCAL DATABASE ENGINE OPERATIONS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticket_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT,
            customer_name TEXT,
            ticket_text TEXT,
            sentiment TEXT,
            urgency_score INTEGER,
            churn_risk_score INTEGER,
            reason TEXT,
            key_phrases TEXT,
            alert_triggered INTEGER,
            alert_reason TEXT,
            processed_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_analysis_to_db(ticket_text, ticket_id, customer_name, analysis, alert_triggered, alert_reason):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ticket_analyses (
            ticket_id, customer_name, ticket_text, sentiment, 
            urgency_score, churn_risk_score, reason, key_phrases, 
            alert_triggered, alert_reason, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticket_id or "UNKNOWN",
        customer_name or "Anonymous",
        ticket_text,
        analysis["sentiment"].lower(),
        analysis["urgency_score"],
        analysis["churn_risk_score"],
        analysis["reason"],
        json.dumps(analysis.get("key_phrases", [])),
        1 if alert_triggered else 0,
        alert_reason,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def load_db_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM ticket_analyses ORDER BY processed_at DESC", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

# --- CORE PROCESSING HOOKS (LLM INTEGRATION & FALLBACK) ---
def get_system_prompt():
    prompt_path = os.path.join("prompts", "classifier_prompt.txt")
    if os.path.exists(prompt_path):
        with open(prompt_path, "r") as f:
            return f.read()
    return "Analyze the customer ticket text. Return a strict JSON matching sentiment, urgency_score, churn_risk_score, reason, key_phrases."

def query_groq(text: str, model_name: str, system_prompt: str) -> dict:
    payload = {
        "model": model_name,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Customer Message: {text}"}
        ],
        "temperature": 0.1
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    url = "https://api.groq.com/openai/v1/chat/completions"
    response = requests.post(url, headers=headers, json=payload, timeout=8)
    response.raise_for_status()
    
    raw_content = response.json()["choices"][0]["message"]["content"]
    cleaned_json = re.sub(r"^```json\s*|```$", "", raw_content.strip(), flags=re.IGNORECASE)
    return json.loads(cleaned_json)

def query_gemini(text: str, system_prompt: str) -> dict:
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API key is missing.")
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{"text": f"{system_prompt}\n\nCustomer Message Input: {text}"}]
        }],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
    }
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    response.raise_for_status()
    
    raw_content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    cleaned_json = re.sub(r"^```json\s*|```$", "", raw_content.strip(), flags=re.IGNORECASE)
    return json.loads(cleaned_json)

def classify_ticket_integrated(text: str) -> dict:
    system_prompt = get_system_prompt()
    
    # 1. Try Llama 3 Primary & Secondary Models via Groq
    if GROQ_API_KEY:
        for model in [GROQ_MODEL_PRIMARY, GROQ_MODEL_FALLBACK]:
            try:
                return query_groq(text, model, system_prompt)
            except Exception as e:
                st.sidebar.warning(f"Groq {model} failed. Trying next node...")
                continue

    # 2. Seamless Fallback Strategy to Google Gemini
    try:
        st.sidebar.info("Executing failover route to Google Gemini processing channel...")
        return query_gemini(text, system_prompt)
    except Exception as e:
        st.sidebar.error(f"Gemini processing fallback loop failed: {e}")

    # 3. Safe Ground Default Data
    return {
        "sentiment": "neutral", "urgency_score": 5, "churn_risk_score": 5,
        "reason": "Multi-LLM failover loop exhausted completely.", "key_phrases": ["System Timeout"]
    }

def generate_ai_draft(text: str, analysis: dict) -> str:
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        return "Thank you for contacting customer support. We are reviewing your record details."
    
    prompt = f"Write an empathetic, concise response under 100 words for this ticket: '{text}' given tone is '{analysis['sentiment']}'."
    
    try:
        if GROQ_API_KEY:
            return query_groq(text, GROQ_MODEL_FALLBACK, prompt).get("reason", "Draft generated locally.")
        else:
            return query_gemini(text, prompt).get("reason", "Draft generated locally.")
    except Exception:
        return "Our customer care agents have been systematically alerted and are managing your request context."

# --- INTEGRATED DISCORD ROUTING CHANNEL ---
def send_integrated_discord_alert(ticket_text, ticket_id, customer_name, analysis, alert_reason):
    if not DISCORD_WEBHOOK_URL:
        return False
    payload = {
        "username": "TicketSense Core Bot",
        "embeds": [{
            "title": "🚨 HIGH POLARITY ESCALATION ALERT",
            "color": 15158332,
            "fields": [
                {"name": "Ticket ID", "value": ticket_id or "N/A", "inline": True},
                {"name": "Customer", "value": customer_name or "Anonymous", "inline": True},
                {"name": "Sentiment", "value": analysis["sentiment"].upper(), "inline": True},
                {"name": "Urgency", "value": f"🔥 {analysis['urgency_score']}/10", "inline": True},
                {"name": "Churn Risk", "value": f"⚠️ {analysis['churn_risk_score']}/10", "inline": True},
                {"name": "Alert Trigger", "value": alert_reason, "inline": False},
                {"name": "AI Logic Reason", "value": analysis["reason"], "inline": False},
                {"name": "Original Message", "value": f"*{ticket_text}*", "inline": False}
            ]
        }]
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        return r.status_code in [200, 204]
    except Exception:
        return False

# --- PRESENTATION LAYER CONFIGURATION (STREAMLIT) ---
st.set_page_config(page_title="TicketSense AI Engine", page_icon="🎫", layout="wide")
init_db()

st.markdown("""
<style>
    .stApp { background-color: #0F1117; }
    [data-testid="metric-container"] { background: #1C1C2E; border: 1px solid #2D2D44; border-radius: 12px; padding: 1rem; }
    .result-card { background: #1C1C2E; border-radius: 14px; padding: 1.5rem; border: 1px solid #2D2D44; }
    .draft-box { background: #0D1F12; border: 1px solid #10B981; border-radius: 10px; padding: 1.2rem; font-size: 0.95rem; color: #D1FAE5; white-space: pre-wrap; }
    .app-header { background: linear-gradient(135deg, #1C1C2E 0%, #2D1B69 100%); border-radius: 16px; padding: 1.5rem 2rem; border: 1px solid #4C1D95; margin-bottom: 1.5rem; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="app-header">
    <div style="color:white; font-size:1.6rem; font-weight:700;">TicketSense <span style="color:#A78BFA;">Integrated Engine</span></div>
    <div style="color:#A78BFA; font-size:0.9rem; margin-top:3px;">Unified Single-Instance Customer Triage Automation Engine</div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🔌 Core System Links")
    if GROQ_API_KEY: st.success("Llama 3 Nodes: Operational")
    else: st.warning("Llama 3 Nodes: No Key")
    
    if GEMINI_API_KEY: st.success("Gemini Safety Layer: Loaded")
    else: st.warning("Gemini Safety Layer: No Key")
    
    if DISCORD_WEBHOOK_URL: st.success("Discord Webhook: Synced")
    else: st.info("Discord Webhook: Local Only")

    urgency_threshold = st.slider("Urgency Alarm Limits", 1, 10, 8)

tab1, tab2 = st.tabs(["🔍 Triage Center", "📊 Database Records"])

with tab1:
    col_in, col_out = st.columns(2, gap="large")
    with col_in:
        t_text = st.text_area("Inbound Customer Message Body Context:", height=160)
        t_id = st.text_input("Ticket Reference Identifier", "TKT-305")
        t_name = st.text_input("Sender Customer Identification Name", "Bharathi Selvaraj")
        process_btn = st.button("⚡ Run Pipeline Analysis", type="primary")

    with col_out:
        if process_btn and t_text.strip():
            with st.spinner("Executing pipeline routines..."):
                analysis_results = classify_ticket_integrated(t_text)
                
                # Check metrics against boundaries
                alert_triggered = False
                alert_reason = "Normal processing operations"
                if analysis_results["urgency_score"] >= urgency_threshold:
                    alert_triggered = True
                    alert_reason = f"Urgency Level Triggered ({analysis_results['urgency_score']}/10)"
                elif analysis_results["churn_risk_score"] >= 8:
                    alert_triggered = True
                    alert_reason = f"High Customer Attrition Risk Triggered ({analysis_results['churn_risk_score']}/10)"
                
                # Handle Discord alert notification
                discord_sent = False
                if alert_triggered:
                    discord_sent = send_integrated_discord_alert(t_text, t_id, t_name, analysis_results, alert_reason)

                # Commit metrics straight to local relational file
                log_analysis_to_db(t_text, t_id, t_name, analysis_results, discord_sent, alert_reason)

                # Output user cards
                st.markdown(f"""
                <div class="result-card">
                    <h4>Identified Mood: {analysis_results['sentiment'].upper()}</h4>
                    <p><b>Decision Context:</b> {analysis_results['reason']}</p>
                    <p>🚨 <b>System Action:</b> {"Alert fired to Discord channel!" if discord_sent else "Logged internally."}</p>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("### ✍️ Generated Agent Solution Draft")
                agent_reply = generate_ai_draft(t_text, analysis_results)
                st.markdown(f'<div class="draft-box">{agent_reply}</div>', unsafe_allow_html=True)

with tab2:
    records_df = load_db_stats()
    if records_df.empty:
        st.info("No logs present in the relational datastore yet.")
    else:
        st.metric("Total App Pipeline Executions", len(records_df))
        st.dataframe(records_df[["ticket_id", "customer_name", "sentiment", "urgency_score", "churn_risk_score", "alert_triggered", "processed_at"]].head(15))