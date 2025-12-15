"""Pydantic models for API requests and responses."""
from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    message: str
    username: str
    password: str
    api_key: Optional[str] = None


class CredentialsSaveRequest(BaseModel):
    username: str
    password: str
    api_key: str


class CredentialsResponse(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
