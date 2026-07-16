"""Pydantic request/response schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProjectBase(BaseModel):
    name: str
    target_url: str
    goals: Optional[str] = None
    max_steps: int = Field(default=100, ge=1, le=5000)
    model: Optional[str] = None
    # Auth: "none" | "basic" | "form" | "mfa"
    auth_type: str = "none"
    username: Optional[str] = None
    login_instructions: Optional[str] = None


class ProjectCreate(ProjectBase):
    password: Optional[str] = None
    # Base32 TOTP secret, only used when auth_type == "mfa".
    secret_key: Optional[str] = None


class ProjectUpdate(ProjectCreate):
    """Same shape as create. Credential fields left as None keep their stored
    value, so editing a project doesn't require retyping its password."""


class ProjectOut(ProjectBase):
    id: str
    model: str
    # Credentials are never returned. These just tell the UI what is on file.
    has_password: bool = False
    has_secret_key: bool = False
    # Status of this project's most recent run, for the projects table.
    last_run_id: Optional[str] = None
    last_run_status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    runs_count: int = 0
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class RunOut(BaseModel):
    id: str
    project_id: Optional[str] = None
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
