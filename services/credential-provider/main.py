import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="UCP Credential Provider")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    user_id: str
    amount: float
    currency: str
    merchant_name: str


class TokenResponse(BaseModel):
    token: str
    type: str
    expires_at: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tokens", response_model=TokenResponse)
def create_token(request: TokenRequest):
    token = f"tok_{uuid.uuid4()}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    return TokenResponse(
        token=token,
        type="PAYMENT_GATEWAY",
        expires_at=expires_at.isoformat(),
    )
