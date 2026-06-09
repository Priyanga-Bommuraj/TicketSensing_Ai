# app/main.py
from fastapi import FastAPI, HTTPException
from app.models import TicketRequest, DraftRequest
from app.classifier import classify_ticket
from app.database import log_analysis
from app.discord_alert import send_discord_alert
from app.drafter import draft_response
from app.config import settings

app = FastAPI(title="TicketSense AI — Triage Engine")

def evaluate_thresholds(urgency: int, churn: int) -> tuple[bool, str]:
    if urgency >= 8:
        return True, f"Critical Urgency detected ({urgency}/10)"
    if churn >= 8:
        return True, f"High Customer Churn Risk detected ({churn}/10)"
    return False, ""

@app.get("/health", tags=["System"])
def health_check():  # Removed async
    return {
        "status": "healthy",
        "groq_configured": bool(settings.GROQ_API_KEY),
        "discord_configured": bool(settings.DISCORD_WEBHOOK_URL)
    }

@app.post("/analyze", tags=["Analysis"])
def analyze_single_ticket(ticket: TicketRequest):  # Removed async
    if not ticket.text.strip():
        raise HTTPException(status_code=400, detail="Ticket message cannot be empty.")
    
    analysis = classify_ticket(ticket.text)
    alert_triggered, alert_reason = evaluate_thresholds(analysis.urgency_score, analysis.churn_risk_score)
    
    alert_sent = False
    if alert_triggered:
        alert_sent = send_discord_alert(ticket, analysis, alert_reason)
        
    log_analysis(ticket, analysis, alert_sent, alert_reason)
    return {
        "status": "success",
        "alert_triggered": alert_sent,
        "alert_reason": alert_reason if alert_triggered else "Below limits.",
        "analysis": analysis.dict()
    }

@app.post("/draft-response", tags=["AI Features"])
def draft_ticket_response(req: DraftRequest):  # Removed async
    draft = draft_response(
        ticket_text=req.ticket_text,
        sentiment=req.sentiment,
        urgency_score=req.urgency_score,
        churn_risk_score=req.churn_risk_score,
        reason=req.reason
    )
    return {"draft": draft, "sentiment": req.sentiment}

@app.post("/analyze/batch", tags=["Analysis"])
def analyze_batch_tickets(tickets: list[TicketRequest]):  # Removed async
    if len(tickets) > 20:
        raise HTTPException(status_code=400, detail="Max 20 tickets per batch.")
    
    results = []
    alert_count = 0
    for ticket in tickets:
        if not ticket.text.strip():
            continue
        try:
            analysis = classify_ticket(ticket.text)
            alert_triggered, alert_reason = evaluate_thresholds(analysis.urgency_score, analysis.churn_risk_score)
            alert_sent = False
            if alert_triggered:
                alert_sent = send_discord_alert(ticket, analysis, alert_reason)
                alert_count += 1
            log_analysis(ticket, analysis, alert_sent, alert_reason)
            results.append({
                "ticket_id": ticket.ticket_id or "UNKNOWN",
                "customer_name": ticket.customer_name or "Anonymous",
                "sentiment": analysis.sentiment,
                "urgency_score": analysis.urgency_score,
                "churn_risk_score": analysis.churn_risk_score,
                "alert_triggered": alert_sent,
                "reason": analysis.reason
            })
        except Exception as e:
            results.append({"ticket_id": ticket.ticket_id or "UNKNOWN", "error": str(e)})
            
    return {"total_processed": len(tickets), "alerts_triggered": alert_count, "results": results}