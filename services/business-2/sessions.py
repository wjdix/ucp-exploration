import os
import uuid

import httpx

from catalog import get_product
from models import (
    Buyer,
    CheckoutSession,
    Fulfillment,
    LineItem,
    LineItemRequest,
    PaymentInstrument,
    Product,
)

_sessions: dict[str, CheckoutSession] = {}

PSP_URL = os.environ.get("PSP_URL", "http://psp:8000")


def _build_line_item(req: LineItemRequest) -> LineItem:
    product_data = get_product(req.product_id)
    if product_data is None:
        raise ValueError(f"Product not found: {req.product_id}")
    product = Product(**product_data)
    line_total = round(product.price * req.quantity, 2)
    return LineItem(
        product_id=req.product_id,
        quantity=req.quantity,
        item=product,
        totals={"subtotal": line_total},
    )


def _compute_totals(line_items: list[LineItem]) -> dict[str, float]:
    subtotal = round(sum(li.totals["subtotal"] for li in line_items), 2)
    return {
        "subtotal": subtotal,
        "tax": 0.0,
        "total": subtotal,
    }


def create_session(line_item_requests: list[LineItemRequest]) -> CheckoutSession:
    session_id = f"cs_{uuid.uuid4().hex[:12]}"
    line_items = [_build_line_item(req) for req in line_item_requests]
    totals = _compute_totals(line_items)
    session = CheckoutSession(
        id=session_id,
        line_items=line_items,
        totals=totals,
    )
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> CheckoutSession | None:
    return _sessions.get(session_id)


def update_session(
    session_id: str,
    buyer: Buyer | None = None,
    fulfillment: Fulfillment | None = None,
) -> CheckoutSession | None:
    session = _sessions.get(session_id)
    if session is None:
        return None

    if buyer is not None:
        session.buyer = buyer
    if fulfillment is not None:
        session.fulfillment = fulfillment

    if session.buyer is not None and session.fulfillment is not None:
        session.status = "ready_for_complete"

    _sessions[session_id] = session
    return session


async def complete_session(
    session_id: str,
    payment: PaymentInstrument,
) -> CheckoutSession | None:
    session = _sessions.get(session_id)
    if session is None:
        return None

    if session.status == "completed":
        return session

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{PSP_URL}/authorize",
            json={
                "token": payment.credential.token,
                "amount": session.totals["total"],
                "currency": "USD",
                "merchant_id": "merchant_demo",
            },
        )
        resp.raise_for_status()
        auth = resp.json()

    session.payment = auth
    session.status = "completed"
    session.order_id = f"order_{uuid.uuid4().hex[:12]}"
    _sessions[session_id] = session
    return session
