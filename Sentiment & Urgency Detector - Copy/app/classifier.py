# app/classifier.py
import json
import re
import os
import requests
from app.config import settings
from app.models import TicketAnalysis

def get_prompt():
    prompt_path = os.path.join("prompts", "classifier_prompt.txt")
    if os.path.exists(prompt_path):
        with open(prompt_path, "r") as f:
            return f.read()
    return "Analyze the customer ticket text. Return a strict JSON matching sentiment, urgency_score, churn_risk_score, reason, key_phrases."

def query_groq(text: str, model_name: str, system_prompt: str) -> TicketAnalysis:
    """Helper executing API requests against Groq hardware cluster nodes"""
    payload = {
        "model": model_name,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Customer Message: {text}"}
        ],
        "temperature": 0.1
    }
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    url = "https://api.groq.com/openai/v1/chat/completions"
    response = requests.post(url, headers=headers, json=payload, timeout=8)
    response.raise_for_status()
    
    raw_content = response.json()["choices"][0]["message"]["content"]
    cleaned_json = re.sub(r"^```json\s*|```$", "", raw_content.strip(), flags=re.IGNORECASE)
    return TicketAnalysis(**json.loads(cleaned_json))

def query_gemini(text: str, system_prompt: str) -> TicketAnalysis:
    """Helper executing API requests against Google Generative Language endpoints"""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("Gemini API key is completely missing from environment configuration.")

    # Using the standard 2026 stable Flash tier endpoint configuration
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "contents": [{
            "parts": [{"text": f"{system_prompt}\n\nCustomer Message Input: {text}"}]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    response.raise_for_status()
    
    raw_content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    cleaned_json = re.sub(r"^```json\s*|```$", "", raw_content.strip(), flags=re.IGNORECASE)
    return TicketAnalysis(**json.loads(cleaned_json))

def classify_ticket(text: str) -> TicketAnalysis:
    system_prompt = get_prompt()

    # STEP 1: ATTEMPT PRIMARY GROQ MODELS (Llama 3 70B -> Llama 3 8B)
    if settings.GROQ_API_KEY:
        for model in [settings.GROQ_MODEL, settings.GROQ_MODEL_FALLBACK]:
            try:
                print(f"[Fallback Layer 1] Pinging Groq Infrastructure Matrix -> Model: {model}")
                return query_groq(text, model, system_prompt)
            except Exception as e:
                print(f"[Fallback Active] Groq node ({model}) failed or rate-limited: {e}")
                continue

    # STEP 2: SECONDARY LEVEL ESCALATION TO GOOGLE GEMINI LAYER
    try:
        print("[Fallback Layer 2] Catch event active. Re-routing runtime traffic downstream to Google Gemini API...")
        return query_gemini(text, system_prompt)
    except Exception as gemini_err:
        print(f"[Fallback Active] Secondary Gemini channel failed: {gemini_err}")

    # STEP 3: LOGICAL SAFEGUARD SYSTEM GROUND STATE DEFAULT
    print("[Fallback Layer 3] Critical Error: Multi-LLM API failover loops exhausted. Executing static safety fallback data.")
    return TicketAnalysis(
        sentiment="neutral", 
        urgency_score=5, 
        churn_risk_score=5,
        reason="Multi-API structural failover strategy engaged automatically due to downstream gateway timeouts.",
        key_phrases=["System Timeout Event"]
    )