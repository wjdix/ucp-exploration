import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI(title="UCP Payment Service Provider")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthorizeRequest(BaseModel):
    token: str
    amount: float
    currency: str
    merchant_id: str


class AuthorizeResponse(BaseModel):
    authorization_id: str
    status: str
    amount: float
    currency: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/authorize", response_model=AuthorizeResponse)
def authorize(request: AuthorizeRequest):
    if not request.token.startswith("tok_"):
        raise HTTPException(status_code=400, detail="Invalid token: must start with 'tok_'")

    return AuthorizeResponse(
        authorization_id=f"auth_{uuid.uuid4().hex}",
        status="approved",
        amount=request.amount,
        currency=request.currency,
    )
