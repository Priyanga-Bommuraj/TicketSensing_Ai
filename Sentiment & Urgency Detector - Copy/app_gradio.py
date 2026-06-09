import os
import re
import json
import sqlite3
import requests
import pandas as pd
from datetime import datetime
import gradio as gr
from dotenv import load_dotenv

# Load environmental variables
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DB_PATH = "ticketsense.db"

# --- DATABASE LAYER INTEGRATION ---
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
            alert_triggered INTEGER,
            alert_reason TEXT,
            processed_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_to_db(ticket_id, name, text, analysis, alert_triggered, alert_reason):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ticket_analyses (
            ticket_id, customer_name, ticket_text, sentiment, 
            urgency_score, churn_risk_score, reason, 
            alert_triggered, alert_reason, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(ticket_id), str(name), str(text),
        analysis["sentiment"].lower(),
        int(analysis["urgency_score"]),
        int(analysis["churn_risk_score"]),
        analysis["reason"],
        1 if alert_triggered else 0,
        alert_reason,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

# --- MULTI-LLM INFERENCE PIPELINE ---
def run_groq(text: str, model: str, system_prompt: str) -> dict:
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Ticket: {text}"}
        ],
        "temperature": 0.1
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload, timeout=8)
    response.raise_for_status()
    raw = response.json()["choices"][0]["message"]["content"]
    return json.loads(re.sub(r"^```json\s*|```$", "", raw.strip(), flags=re.IGNORECASE))

def run_gemini(text: str, system_prompt: str) -> dict:
    if not GEMINI_API_KEY:
        raise ValueError("Gemini key unconfigured.")
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": f"{system_prompt}\n\nTicket Context: {text}"}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
    }
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    response.raise_for_status()
    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(re.sub(r"^```json\s*|```$", "", raw.strip(), flags=re.IGNORECASE))

def analyze_ticket_core(text: str) -> dict:
    system_prompt = "Analyze the customer ticket text. Return a strict JSON matching keys: sentiment, urgency_score (1-10), churn_risk_score (1-10), reason."
    
    if GROQ_API_KEY:
        for model in ["llama3-70b-8192", "llama3-8b-8192"]:
            try:
                return run_groq(text, model, system_prompt)
            except Exception:
                continue
    try:
        return run_gemini(text, system_prompt)
    except Exception:
        return {"sentiment": "neutral", "urgency_score": 5, "churn_risk_score": 5, "reason": "Fallback default triggered."}

# --- DISCORD COLLABORATION INTEGRATION ---
def send_discord_alert(ticket_id, name, text, analysis, reason):
    if not DISCORD_WEBHOOK_URL:
        return False
    payload = {
        "username": "TicketSense Tracker",
        "embeds": [{
            "title": "🚨 ESCALATED INBOUND COMPLAINT",
            "color": 16767320,  # Signature Mustard Yellow Accent Code
            "fields": [
                {"name": "Ticket ID", "value": str(ticket_id), "inline": True},
                {"name": "Customer", "value": str(name), "inline": True},
                {"name": "Metrics", "value": f"🔥 Urgency: {analysis['urgency_score']}/10 | ⚠️ Churn: {analysis['churn_risk_score']}/10", "inline": False},
                {"name": "Trigger Condition", "value": reason, "inline": False},
                {"name": "AI Reason", "value": analysis["reason"], "inline": False},
                {"name": "Message Snippet", "value": f"*{text[:200]}...*", "inline": False}
            ]
        }]
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        return r.status_code in [200, 204]
    except Exception:
        return False

# --- GRADIO EXECUTION LOGIC ROUTINES ---
def process_batch_csv(file_obj, threshold_val):
    if file_obj is None:
        return "Please upload a valid CSV file first.", None
    
    try:
        # Load the uploaded dataset
        df = pd.read_csv(file_obj.name)
        
        # Standardize expected columns to keep it user-friendly
        required = ['ticket_id', 'customer_name', 'ticket_text']
        for col in required:
            if col not in df.columns:
                return f"Missing required column layout: '{col}'. Your CSV must contain ticket_id, customer_name, and ticket_text.", None

        # Storage arrays for results
        sentiments, urgency_scores, churn_scores, ai_reasons, alert_status = [], [], [], [], []

        # Iterate through data rows sequentially
        for _, row in df.iterrows():
            text = str(row['ticket_text'])
            
            # Execute analysis pipeline
            analysis = analyze_ticket_core(text)
            
            # Boundary threshold valuation
            triggered = False
            cause = "Nominal"
            if analysis["urgency_score"] >= threshold_val:
                triggered = True
                cause = f"Urgency Violation ({analysis['urgency_score']}/10)"
            elif analysis["churn_risk_score"] >= 8:
                triggered = True
                cause = f"High Churn Risk Language ({analysis['churn_risk_score']}/10)"
                
            # Dispatch Discord Alert if flagged
            discord_confirmed = False
            if triggered:
                discord_confirmed = send_discord_alert(row['ticket_id'], row['customer_name'], text, analysis, cause)

            # Save operation to SQLite instance
            log_to_db(row['ticket_id'], row['customer_name'], text, analysis, discord_confirmed, cause)
            
            # Append rows back to display dataframe
            sentiments.append(analysis["sentiment"].upper())
            urgency_scores.append(analysis["urgency_score"])
            churn_scores.append(analysis["churn_risk_score"])
            ai_reasons.append(analysis["reason"])
            alert_status.append("🔴 Dispatched" if discord_confirmed else "🟢 Logged Locally")

        # Mutate the dataframe with calculated values
        df["Detected Tone"] = sentiments
        df["Urgency Rating"] = urgency_scores
        df["Churn Index"] = churn_scores
        df["AI Logic Assessment"] = ai_reasons
        df["Action Status"] = alert_status

        # Create output path for download
        output_path = "processed_tickets_summary.csv"
        df.to_csv(output_path, index=False)

        summary_msg = f"Processed {len(df)} tickets successfully. Databases committed, Discord channels alerted where matching rules applied."
        return summary_msg, df

    except Exception as e:
        return f"Error processing file layout context: {str(e)}", None

def get_database_ledger():
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT ticket_id, customer_name, sentiment, urgency_score, churn_risk_score, alert_triggered, processed_at FROM ticket_analyses ORDER BY processed_at DESC", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame(columns=["Status", "Logs Available"])

# --- PREMIUM STYLING & GRADIO WORKSPACE ---
init_db()

# Custom Theme Design - Charcoal with Slate Panels and Mustard Yellow highlights
custom_theme = gr.themes.Default(
    primary_hue="yellow",
    secondary_hue="slate",
    neutral_hue="zinc"
).set(
    body_background_fill="#0F1115",
    block_background_fill="#1A1D24",
    block_border_color="#2D333F",
    button_primary_background_fill="#FFDB58",
    button_primary_text_color="#0F1115"
)

with gr.Blocks(theme=custom_theme, title="TicketSense Engine Workspace") as demo:
    gr.HTML("""
    <div style='background: linear-gradient(135deg, #1A1D24 0%, #11141A 100%); padding: 20px; border-left: 6px solid #FFDB58; border-radius: 6px; margin-bottom: 20px;'>
        <h2 style='color: white; margin: 0; font-family: system-ui;'>⚙️ TICKET<span style='color:#FFDB58;'>SENSE</span> AI — BATCH PARSING ENVIRONMENT</h2>
        <p style='color: #8E9AA8; margin: 5px 0 0 0; font-size: 0.95rem;'>Integrated Processing Node • Asynchronous Fallback Validation</p>
    </div>
    """)
    
    with gr.Tabs():
        with gr.TabItem("📊 CSV Processing Control Board"):
            gr.Markdown("### Upload Bulk Tickets Document (`.csv`)")
            
            with gr.Row():
                with gr.Column(scale=1):
                    file_input = gr.File(label="Target Source Document", file_types=[".csv"])
                    threshold_slider = gr.Slider(minimum=1, maximum=10, value=8, step=1, label="Urgency Metric Alert Trigger Bounds")
                    run_btn = gr.Button("INITIALIZE BATCH ENGINE RUN", variant="primary")
                
                with gr.Column(scale=2):
                    status_output = gr.Textbox(label="Operational Engine Status logs", interactive=False)
                    table_output = gr.Dataframe(label="Real-time Evaluation Metrics Array")
            
            run_btn.click(
                fn=process_batch_csv,
                inputs=[file_input, threshold_slider],
                outputs=[status_output, table_output]
            )
            
        with gr.TabItem("🗄️ Relational Ledger System"):
            gr.Markdown("### Direct Database Records")
            refresh_btn = gr.Button("SYNC LEDGER VIEWER", variant="secondary")
            ledger_table = gr.Dataframe(value=get_database_ledger, interactive=False)
            
            refresh_btn.click(fn=get_database_ledger, outputs=ledger_table)

if __name__ == "__main__":
    demo.launch(server_port=7860)