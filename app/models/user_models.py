from typing import Optional
from pydantic import BaseModel


class Transaction(BaseModel):
    id: str
    type: str
    amount: float
    date: str
    status: str
    description: str


class User(BaseModel):
    user_id: str
    name: str
    email: str
    account_status: str
    kyc_verified: bool
    plan: str
    since: str
    transfer_limit_daily: float
    transfer_limit_remaining: float
    failed_login_attempts: int
    transactions: list[Transaction] = []


class Ticket(BaseModel):
    ticket_id: str
    user_id: str
    issue: str
    priority: str
    status: str
    created_at: str
    estimated_resolution: str
