"""MCP tool definitions for UCP shopping capabilities.

These tools expose the Business service's UCP checkout capabilities
via the Model Context Protocol, allowing AI agents to auto-discover
available commerce operations.
"""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from catalog import list_products, get_product
from models import (
    Buyer,
    Fulfillment,
    FulfillmentDestination,
    LineItemRequest,
    PaymentCredential,
    PaymentInstrument,
    PostalAddress,
)
from sessions import complete_session, create_session, get_session, update_session

mcp = FastMCP(
    "UCP Book Store",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


@mcp.tool()
def browse_products() -> list[dict]:
    """Browse the product catalog. Returns all available products with their
    id, title, description, price, and currency."""
    return list_products()


@mcp.tool()
def get_product_details(product_id: str) -> dict:
    """Get detailed information about a specific product.

    Args:
        product_id: The product identifier (e.g. "prod_b001")
    """
    product = get_product(product_id)
    if product is None:
        return {"error": f"Product not found: {product_id}"}
    return product


@mcp.tool()
def create_checkout(items: list[dict]) -> dict:
    """Create a new UCP checkout session with the selected products.

    Args:
        items: List of items to purchase. Each item should have
               "product_id" (string) and "quantity" (integer, default 1).
               Example: [{"product_id": "prod_b001", "quantity": 2}]
    """
    line_item_requests = [
        LineItemRequest(product_id=item["product_id"], quantity=item.get("quantity", 1))
        for item in items
    ]
    try:
        session = create_session(line_item_requests)
    except ValueError as e:
        return {"error": str(e)}
    return session.model_dump(mode="json")


@mcp.tool()
def update_checkout(
    session_id: str,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    street_address: str | None = None,
    city: str | None = None,
    state: str | None = None,
    postal_code: str | None = None,
    country: str = "US",
) -> dict:
    """Update a checkout session with buyer information and/or shipping address.

    Provide buyer details (email, first_name, last_name) and shipping address
    fields to progress the checkout. Once both buyer and shipping are provided,
    the session becomes ready for payment completion.

    Args:
        session_id: The checkout session ID returned from create_checkout
        email: Buyer's email address
        first_name: Buyer's first name
        last_name: Buyer's last name
        street_address: Shipping street address
        city: Shipping city
        state: Shipping state/region
        postal_code: Shipping postal/zip code
        country: Shipping country code (default "US")
    """
    buyer = None
    if email and first_name and last_name:
        buyer = Buyer(email=email, first_name=first_name, last_name=last_name)

    fulfillment = None
    if street_address and city and state and postal_code:
        address = PostalAddress(
            street_address=street_address,
            address_locality=city,
            address_region=state,
            postal_code=postal_code,
            address_country=country,
        )
        fulfillment = Fulfillment(
            destinations=[FulfillmentDestination(type="shipping", address=address)]
        )

    session = update_session(session_id, buyer=buyer, fulfillment=fulfillment)
    if session is None:
        return {"error": f"Session not found: {session_id}"}
    return session.model_dump(mode="json")


@mcp.tool()
async def complete_checkout(
    session_id: str,
    payment_token: str,
    payment_type: str = "PAYMENT_GATEWAY",
) -> dict:
    """Complete a checkout session by submitting payment. This finalizes the
    purchase and creates an order.

    The payment token should be obtained from the Credential Provider before
    calling this tool.

    Args:
        session_id: The checkout session ID
        payment_token: The tokenized payment credential from the Credential Provider
        payment_type: Payment type (default "PAYMENT_GATEWAY")
    """
    payment = PaymentInstrument(
        credential=PaymentCredential(type=payment_type, token=payment_token)
    )
    session = await complete_session(session_id, payment=payment)
    if session is None:
        return {"error": f"Session not found: {session_id}"}
    return session.model_dump(mode="json")
