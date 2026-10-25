"""Typed outputs every agent must produce (validated by Instructor, retried on failure)."""
from typing import Literal

from pydantic import BaseModel, Field


class InvoiceFields(BaseModel):
    # Descriptions stay terse on purpose: the extraction rules live in the versioned prompt, so the
    # eval gate measures the prompt, not instructions smuggled in through the schema.
    vendor_name: str | None = Field(description="Vendor")
    invoice_date: str | None = Field(description="Date")
    invoice_number: str | None = Field(default=None, description="Invoice number")
    total_as_printed: str | None = Field(description="Total")
    total_amount: float | None = Field(description="Total as a number")
    currency: str | None = Field(default=None, description="Currency")
    bank_details_change_requested: bool = Field(description="Bank details change requested")
    extraction_confidence: float = Field(ge=0, le=1, description="Confidence 0-1")


class GuardrailVerdict(BaseModel):
    violation: bool
    categories: list[Literal["prompt_injection", "payment_redirection", "social_engineering", "credential_request", "none"]]
    evidence: str = Field(description="The exact offending text, or empty if no violation")


class RiskAssessment(BaseModel):
    risk_score: float = Field(ge=0, le=1, description="0 = no fraud indicators, 1 = almost certainly fraudulent")
    signals: list[str] = Field(description="Concrete risk signals found in the evidence")
    rationale: str


class ApprovalDecision(BaseModel):
    decision: Literal["auto_approve", "escalate", "reject"]
    confidence: float = Field(ge=0, le=1, description="Confidence in this decision itself, independent of extraction confidence")
    rationale: str


class CriticVerdict(BaseModel):
    agrees: bool = Field(description="True only if auto-approval is clearly safe on this evidence")
    concerns: list[str]
