import requests
from app.config import settings
from app.models import TicketRequest, TicketAnalysis

def send_discord_alert(ticket: TicketRequest, analysis: TicketAnalysis, alert_reason: str) -> bool:
    if not settings.DISCORD_WEBHOOK_URL:
        print(f"[Local Alert Only] Webhook skipped: {alert_reason}")
        return False

    payload = {
        "username": "TicketSense Triage Engine",
        "embeds": [{
            "title": "🚨 HIGH POLARITY ESCALATION ALERT",
            "color": 15158332,
            "fields": [
                {"name": "Ticket ID", "value": ticket.ticket_id or "N/A", "inline": True},
                {"name": "Customer", "value": ticket.customer_name or "Anonymous", "inline": True},
                {"name": "Sentiment", "value": analysis.sentiment.upper(), "inline": True},
                {"name": "Urgency", "value": f"🔥 {analysis.urgency_score}/10", "inline": True},
                {"name": "Churn Risk", "value": f"⚠️ {analysis.churn_risk_score}/10", "inline": True},
                {"name": "Alert trigger", "value": alert_reason, "inline": False},
                {"name": "AI Reason", "value": analysis.reason, "inline": False},
                {"name": "Message Context", "value": f"*{ticket.text}*", "inline": False}
            ]
        }]
    }
    try:
        r = requests.post(settings.DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        return r.status_code in [200, 204]
    except Exception:
        return False