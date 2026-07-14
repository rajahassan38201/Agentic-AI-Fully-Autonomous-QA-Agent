"""Pydantic request/response schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class RunCreate(BaseModel):
    target_url: str
    goals: Optional[str] = None
    max_steps: int = 100
    model: Optional[str] = None
    viewport_width: Optional[int] = None
    viewport_height: Optional[int] = None
    # Auth: "none" | "basic" | "form" | "mfa"
    auth_type: str = "none"
    username: Optional[str] = None
    password: Optional[str] = None
    # Base32 TOTP secret, only used when auth_type == "mfa".
    secret_key: Optional[str] = None
    login_instructions: Optional[str] = None


class RunOut(BaseModel):
    id: str
    target_url: str
    goals: Optional[str]
    status: str
    summary: Optional[str]
    error: Optional[str]
    steps_count: int
    findings_count: int
    config: Optional[dict]
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    has_video: bool = False
    created_at: Optional[datetime]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True


class FindingOut(BaseModel):
    id: str
    title: str
    severity: str
    category: Optional[str]
    description: Optional[str]
    steps_to_reproduce: Optional[str]
    expected: Optional[str]
    actual: Optional[str]
    evidence: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class StepOut(BaseModel):
    id: str
    index: int
    tool_name: str
    tool_input: Optional[str]
    result_summary: Optional[str]
    is_error: bool
    created_at: Optional[datetime]

    class Config:
        from_attributes = True
