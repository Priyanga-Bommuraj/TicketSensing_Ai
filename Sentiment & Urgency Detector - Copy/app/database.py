import sqlite3
import json
from datetime import datetime
from app.config import settings
from app.models import TicketRequest, TicketAnalysis

def init_db():
    conn = sqlite3.connect(settings.DB_PATH)
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

def log_analysis(ticket: TicketRequest, analysis: TicketAnalysis, alert_triggered: bool, alert_reason: str):
    conn = sqlite3.connect(settings.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ticket_analyses (
            ticket_id, customer_name, ticket_text, sentiment, 
            urgency_score, churn_risk_score, reason, key_phrases, 
            alert_triggered, alert_reason, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticket.ticket_id or "UNKNOWN",
        ticket.customer_name or "Anonymous",
        ticket.text,
        analysis.sentiment.lower(),
        analysis.urgency_score,
        analysis.churn_risk_score,
        analysis.reason,
        json.dumps(analysis.key_phrases),
        1 if alert_triggered else 0,
        alert_reason,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

init_db()