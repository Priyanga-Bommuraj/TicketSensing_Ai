from pydantic import BaseModel, Field
from typing import List, Optional

class TicketRequest(BaseModel):
    text: str = Field(..., description="The raw customer message text")
    ticket_id: Optional[str] = None
    customer_name: Optional[str] = None

class TicketAnalysis(BaseModel):
    sentiment: str = Field(description="Must be exactly: angry, frustrated, neutral, or satisfied")
    urgency_score: int = Field(description="Urgency scale from 1 to 10")
    churn_risk_score: int = Field(description="Churn risk scale from 1 to 10")
    reason: str = Field(description="A single-sentence explanation of the score")
    key_phrases: List[str] = Field(description="Top 3 phrases causing this classification")

class DraftRequest(BaseModel):
    ticket_text: str
    sentiment: str
    urgency_score: int
    churn_risk_score: int
    reason: str