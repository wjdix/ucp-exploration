"""Aggregator MCP tools that proxy to multiple business stores."""
import json
import httpx
from mcp.server.fastmcp import FastMCP
from store_registry import StoreConfig, load_stores

mcp = FastMCP(
    "UCP Store Aggregator",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)

_stores: list[StoreConfig] = []
_session_store_map: dict[str, str] = {}  # session_id -> store_id


def init_stores():
    global _stores
    _stores = load_stores()


async def _call_store_tool(store: StoreConfig, tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool on a specific store via JSON-RPC over HTTP."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Initialize MCP session
        init_resp = await client.post(store.mcp_url, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "aggregator", "version": "1.0"}
            }
        }, headers={"Accept": "application/json", "Content-Type": "application/json"})

        # Send initialized notification
        await client.post(store.mcp_url, json={
            "jsonrpc": "2.0", "method": "notifications/initialized"
        }, headers={"Accept": "application/json", "Content-Type": "application/json"})

        # Call the tool
        resp = await client.post(store.mcp_url, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments}
        }, headers={"Accept": "application/json", "Content-Type": "application/json"})
        resp.raise_for_status()
        result = resp.json()

        if "error" in result:
            return {"error": result["error"]}

        mcp_result = result.get("result", {})

        # Prefer structuredContent which has the parsed data directly
        structured = mcp_result.get("structuredContent", {})
        if "result" in structured:
            return structured["result"]

        # Fallback: parse text content entries
        content = mcp_result.get("content", [])
        parsed = []
        for item in content:
            if item.get("type") == "text":
                try:
                    parsed.append(json.loads(item["text"]))
                except (json.JSONDecodeError, KeyError):
                    pass
        if len(parsed) == 1:
            return parsed[0]
        if parsed:
            return parsed
        return mcp_result


def _get_store(store_id: str) -> StoreConfig | None:
    for s in _stores:
        if s.store_id == store_id:
            return s
    return None


@mcp.tool()
async def search_products(query: str = "") -> list[dict]:
    """Search for products across all stores. Returns products from every registered store with store_id and store_name fields added.

    Args:
        query: Optional search term to filter products by title or description. Leave empty to browse all products.
    """
    all_products = []
    for store in _stores:
        try:
            products = await _call_store_tool(store, "browse_products", {})
            if isinstance(products, list):
                for p in products:
                    p["store_id"] = store.store_id
                    p["store_name"] = store.name
                    all_products.append(p)
        except Exception as e:
            all_products.append({"error": f"Failed to reach {store.name}: {str(e)}", "store_id": store.store_id})

    if query:
        q = query.lower()
        all_products = [
            p for p in all_products
            if "error" in p or q in p.get("title", "").lower() or q in p.get("description", "").lower()
        ]

    return all_products


@mcp.tool()
async def create_checkout(store_id: str, items: list[dict]) -> dict:
    """Create a checkout session at a specific store.

    Args:
        store_id: The store to create the checkout at (from search_products results)
        items: List of items to purchase. Each item should have "product_id" and "quantity".
    """
    store = _get_store(store_id)
    if store is None:
        return {"error": f"Store not found: {store_id}"}

    result = await _call_store_tool(store, "create_checkout", {"items": items})

    # Track which store owns this session
    if isinstance(result, dict) and "id" in result:
        _session_store_map[result["id"]] = store_id

    return result


@mcp.tool()
async def update_checkout(
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

    Args:
        session_id: The checkout session ID from create_checkout
        email: Buyer's email address
        first_name: Buyer's first name
        last_name: Buyer's last name
        street_address: Shipping street address
        city: Shipping city
        state: Shipping state/region
        postal_code: Shipping postal/zip code
        country: Shipping country code (default "US")
    """
    store_id = _session_store_map.get(session_id)
    if store_id is None:
        return {"error": f"Session not found in aggregator: {session_id}"}

    store = _get_store(store_id)
    if store is None:
        return {"error": f"Store not found: {store_id}"}

    args = {"session_id": session_id}
    if email is not None: args["email"] = email
    if first_name is not None: args["first_name"] = first_name
    if last_name is not None: args["last_name"] = last_name
    if street_address is not None: args["street_address"] = street_address
    if city is not None: args["city"] = city
    if state is not None: args["state"] = state
    if postal_code is not None: args["postal_code"] = postal_code
    if country != "US": args["country"] = country

    return await _call_store_tool(store, "update_checkout", args)


@mcp.tool()
async def complete_checkout(
    session_id: str,
    payment_token: str,
    payment_type: str = "PAYMENT_GATEWAY",
) -> dict:
    """Complete a checkout session by submitting payment.

    Args:
        session_id: The checkout session ID
        payment_token: The tokenized payment credential from the Credential Provider
        payment_type: Payment type (default "PAYMENT_GATEWAY")
    """
    store_id = _session_store_map.get(session_id)
    if store_id is None:
        return {"error": f"Session not found in aggregator: {session_id}"}

    store = _get_store(store_id)
    if store is None:
        return {"error": f"Store not found: {store_id}"}

    return await _call_store_tool(store, "complete_checkout", {
        "session_id": session_id,
        "payment_token": payment_token,
        "payment_type": payment_type,
    })
