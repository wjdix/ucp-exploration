import contextlib

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from catalog import get_product, list_products
from mcp_tools import mcp
from models import (
    CompleteCheckoutRequest,
    CreateCheckoutRequest,
    Product,
    UpdateCheckoutRequest,
)
from sessions import complete_session, create_session, get_session, update_session


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="UCP Business Service", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount MCP server at /mcp for tool auto-discovery
app.mount("/mcp", mcp.streamable_http_app())


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/.well-known/ucp")
async def ucp_discovery():
    return {
        "ucp_version": "2026-01-11",
        "business": {
            "name": "Demo Electronics Store",
            "url": "http://localhost:8001",
        },
        "capabilities": [
            {
                "id": "dev.ucp.shopping.checkout",
                "version": "2026-01-11",
                "rest": {
                    "base_url": "http://localhost:8001",
                },
                "mcp": {
                    "endpoint": "http://localhost:8001/mcp/",
                },
            }
        ],
        "payment_handlers": [
            {
                "id": "demo_payment_gateway",
                "type": "PAYMENT_GATEWAY",
                "name": "Demo Payment Gateway",
            }
        ],
    }


@app.get("/products")
async def list_all_products() -> list[Product]:
    return [Product(**p) for p in list_products()]


@app.get("/products/{product_id}")
async def get_single_product(product_id: str) -> Product:
    product_data = get_product(product_id)
    if product_data is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return Product(**product_data)


@app.post("/checkout-sessions")
async def create_checkout_session(body: CreateCheckoutRequest):
    try:
        session = create_session(body.line_items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return session


@app.get("/checkout-sessions/{session_id}")
async def get_checkout_session(session_id: str):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.put("/checkout-sessions/{session_id}")
async def update_checkout_session(session_id: str, body: UpdateCheckoutRequest):
    session = update_session(session_id, buyer=body.buyer, fulfillment=body.fulfillment)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/checkout-sessions/{session_id}/complete")
async def complete_checkout(session_id: str, body: CompleteCheckoutRequest):
    session = await complete_session(session_id, payment=body.payment)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
