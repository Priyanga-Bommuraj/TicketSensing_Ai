import requests
from app.config import settings

DRAFT_SYSTEM_PROMPT = """You are an expert customer support response writer.
Write a professional, empathetic, and action-oriented response for an agent to send.
- angry: Apologize sincerely. Be direct. Offer immediate escalation.
- frustrated: Acknowledge the delay/issue. Show ownership.
- neutral: Professional and clear next steps.
- satisfied: Thank them warmly.
Keep it under 150 words. Output ONLY the response text."""

def draft_response(ticket_text: str, sentiment: str, urgency_score: int, churn_risk_score: int, reason: str) -> str:
    if not settings.GROQ_API_KEY:
        return "Thank you for your message. Our team has been notified and is looking into this layout immediately."

    payload = {
        "model": settings.GROQ_MODEL_FALLBACK,
        "messages": [
            {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Ticket: {ticket_text}\nSentiment: {sentiment}, Urgency: {urgency_score}, Reasoning: {reason}"}
        ],
        "temperature": 0.4
    }
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"}
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Draft generation unavailable: {str(e)}"