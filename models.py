"""
models.py — Pydantic request/response schemas for all API routes.
"""

from typing import List, Optional
from pydantic import BaseModel


# ── User ──────────────────────────────────────────────────────────
class UserRegister(BaseModel):
    telegram_id: int
    username: Optional[str] = None

class UserResponse(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    main_balance: float = 0.0
    pending_balance: float = 0.0
    total_completed_gmails: int = 0
    total_strikes: int = 0
    is_banned: bool = False
    block_until: Optional[str] = None
    created_at: Optional[str] = None

class UserBanAction(BaseModel):
    ban: bool

class BalanceResponse(BaseModel):
    main_balance: float
    pending_balance: float


# ── Admin Auth ────────────────────────────────────────────────────
class AdminLogin(BaseModel):
    username: str
    password: str

class AdminCreate(BaseModel):
    username: str
    password: str
    role: str = "admin"

class AdminResponse(BaseModel):
    id: int
    username: str
    role: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Bot Settings ──────────────────────────────────────────────────
class BotSettingUpdate(BaseModel):
    key_name: str
    key_value: str

class BotSettingsBulkUpdate(BaseModel):
    settings: List[BotSettingUpdate]


# ── Withdrawals ──────────────────────────────────────────────────
class WithdrawalRequest(BaseModel):
    telegram_id: int
    method: str
    wallet_or_number: str
    amount: float

class WithdrawalResponse(BaseModel):
    id: int
    telegram_id: int
    method: str
    wallet_or_number: str
    amount: float
    status: str
    requested_at: Optional[str] = None


# ── Submissions ──────────────────────────────────────────────────
class SubmissionCreate(BaseModel):
    telegram_id: int
    submission_type: str
    email: str
    password: str
    secret_key_2fa: Optional[str] = None

class SubmissionResponse(BaseModel):
    id: int
    telegram_id: int
    submission_type: str
    email: str
    password: str
    secret_key_2fa: Optional[str] = None
    status: str
    submitted_at: Optional[str] = None


# ── Gmail Pool ───────────────────────────────────────────────────
class GmailPoolEntry(BaseModel):
    email: str
    password: str
    recovery_email: Optional[str] = None

class GmailPoolBulkUpload(BaseModel):
    entries: List[GmailPoolEntry]

class GmailPoolResponse(BaseModel):
    id: int
    email: str
    password: str
    recovery_email: Optional[str] = None
    is_assigned: bool = False


# ── Owner Operations ─────────────────────────────────────────────
class BalanceAdjustment(BaseModel):
    telegram_id: int
    amount: float
    owner_password: str


# ── Export ────────────────────────────────────────────────────────
class ExportRequest(BaseModel):
    submission_type: str


# ── Dashboard ────────────────────────────────────────────────────
class DashboardStats(BaseModel):
    total_users: int
    pending_submissions: int
    pending_withdrawals: int
    pool_size: int
    pool_available: int


# ── Generic ──────────────────────────────────────────────────────
class MessageResponse(BaseModel):
    message: str

class AssignTaskResponse(BaseModel):
    email: str
    password: str
    recovery_email: Optional[str] = None
