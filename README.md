# UCP Agentic Commerce Demo

A sample implementation of agentic commerce using the [Universal Commerce Protocol (UCP)](https://ucp.dev/). An AI shopping assistant guides users through product discovery and checkout — entirely through a chat interface.

UCP is an open standard co-developed by Google, Shopify, Etsy, Walmart, Target, and Wayfair that defines how platforms, AI agents, and businesses conduct commerce.

## Architecture

This demo implements the four UCP participants as separate services:

```
┌──────────────────────────────────────────────────────┐
│         Next.js Chat App (Platform / Agent)          │
│         Vercel AI SDK + Claude tool calling          │
│                   localhost:3000                     │
└────────┬──────────────────┬──────────────┬───────────┘
         │ MCP (auto-       │ REST         │
         │ discovered       │              │
         │ tools)           │              │
         ▼                  ▼              ▼
┌─────────────┐   ┌─────────────┐   ┌───────────┐
│  Business   │   │ Credential  │   │    PSP    │
│  (Merchant) │   │  Provider   │   │ (Payment  │
│  :8001      │   │  :8002      │   │  Gateway) │
│  MCP + REST │   │  REST       │   │  :8003    │
└──────┬──────┘   └─────────────┘   └───────────┘
       │                                  ▲
       └──────── authorize payment ───────┘
```

The AI agent **auto-discovers** the merchant's checkout capabilities via MCP (Model Context Protocol). The Business service exposes an MCP server at `/mcp/` that advertises tools like `browse_products`, `create_checkout`, `update_checkout`, and `complete_checkout`. The agent doesn't need hardcoded knowledge of these tools -- it discovers them at runtime from the merchant's MCP endpoint, which is advertised in the UCP discovery document at `/.well-known/ucp`.

The Credential Provider remains a direct REST call since it's a separate UCP participant (not part of the merchant's capabilities).

| Service | Role | Port |
|---------|------|------|
| **Frontend** | AI shopping assistant chat UI. Auto-discovers merchant tools via MCP. | 3000 |
| **Business** | UCP-compliant merchant. Exposes MCP server for tool discovery + REST API for checkout. | 8001 |
| **Credential Provider** | Simulates a digital wallet (e.g. Google Wallet, Apple Pay). Issues tokenized payment credentials. | 8002 |
| **PSP** | Simulates a payment processor (e.g. Stripe, Adyen). Authorizes payment tokens. | 8003 |

## Project Layout

```
ucp-example/
├── docker-compose.yml                 # Runs all backend services
├── frontend/                          # Next.js chat app (Platform/Agent)
│   ├── app/
│   │   ├── page.tsx                   # Chat UI using useChat hook
│   │   └── api/chat/route.ts         # AI agent: MCP client + tool orchestration
│   └── lib/tools.ts                   # Credential Provider tool (direct REST)
│
└── services/
    ├── business/                      # Python/FastAPI merchant service
    │   ├── main.py                    # FastAPI app: REST routes + MCP server mount
    │   ├── mcp_tools.py               # MCP tool definitions (auto-discovered by agents)
    │   ├── models.py                  # Pydantic models (CheckoutSession, Buyer, etc.)
    │   ├── catalog.py                 # In-memory product catalog (4 electronics items)
    │   ├── sessions.py                # Checkout session store + PSP integration
    │   ├── Dockerfile
    │   └── pyproject.toml
    │
    ├── credential-provider/           # Python/FastAPI credential provider
    │   ├── main.py                    # POST /tokens — issues fake payment tokens
    │   ├── Dockerfile
    │   └── pyproject.toml
    │
    └── psp/                           # Python/FastAPI payment service provider
        ├── main.py                    # POST /authorize — approves payment tokens
        ├── Dockerfile
        └── pyproject.toml
```

## Quickstart

### Prerequisites

- Docker & Docker Compose
- Node.js >= 20
- An Anthropic API key

### 1. Start backend services

```sh
docker compose up --build
```

This starts the Business, Credential Provider, and PSP services.

### 2. Start the frontend

```sh
cd frontend
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env.local
npm install
npm run dev
```

### 3. Open the chat

Navigate to [http://localhost:3000](http://localhost:3000) and start shopping.

## Key Interactions

### MCP Tool Discovery

On each chat request, the AI agent connects to the Business service's MCP endpoint and discovers available tools. No tools are hardcoded in the frontend — the merchant defines what operations are available.

```mermaid
sequenceDiagram
    participant Agent as AI Agent<br/>(Platform)
    participant Business as Business<br/>:8001/mcp/

    Agent->>Business: POST /mcp/ {method: "initialize"}
    Business-->>Agent: {serverInfo: "UCP Business Service", capabilities: {tools: ...}}
    Agent->>Business: POST /mcp/ {method: "tools/list"}
    Business-->>Agent: [browse_products, get_product_details,<br/>create_checkout, update_checkout, complete_checkout]

    Note over Agent: Agent now knows what commerce<br/>operations this merchant supports
```

### Product Discovery

The user asks what's available. The AI agent calls the auto-discovered `browse_products` tool.

```mermaid
sequenceDiagram
    participant User
    participant Agent as AI Agent<br/>(Platform)
    participant Business as Business<br/>:8001

    User->>Agent: "What products do you have?"
    Agent->>Business: MCP tool call: browse_products()
    Business-->>Agent: [{id: "prod_001", title: "Wireless Headphones", price: 79.99}, ...]
    Agent->>User: "Here's what's available:<br/>- Wireless Headphones ($79.99)<br/>- USB-C Hub ($49.99)<br/>- Mechanical Keyboard ($129.99)<br/>- Laptop Stand ($39.99)"
```

### Checkout Session Creation

The user picks items. The agent creates a checkout session with the Business.

```mermaid
sequenceDiagram
    participant User
    participant Agent as AI Agent<br/>(Platform)
    participant Business as Business<br/>:8001

    User->>Agent: "I'll take the headphones and the keyboard"
    Agent->>Business: MCP tool call: create_checkout(<br/>items=[{product_id: "prod_001", quantity: 1},<br/>{product_id: "prod_003", quantity: 1}])
    Business-->>Agent: {id: "cs_...", status: "incomplete",<br/>totals: {subtotal: 209.98, total: 209.98}}
    Agent->>User: "Checkout started. Total: $209.98.<br/>I need your name, email, and shipping address."
```

### Checkout Update (Buyer Info + Shipping)

The user provides personal and shipping details. The agent updates the session.

```mermaid
sequenceDiagram
    participant User
    participant Agent as AI Agent<br/>(Platform)
    participant Business as Business<br/>:8001

    User->>Agent: "Jane Smith, jane@example.com,<br/>456 Oak Ave, Portland OR 97201"
    Agent->>Business: MCP tool call: update_checkout(<br/>session_id, email, first_name, last_name,<br/>street_address, city, state, postal_code)
    Business-->>Agent: {status: "ready_for_complete", ...}
    Agent->>User: "Order ready. Ship to Jane Smith, Portland OR.<br/>Total: $209.98. Process payment?"
```

### Payment & Order Completion

The user confirms. The agent obtains a payment token from the Credential Provider, then completes the checkout. The Business service authorizes the payment through the PSP.

```mermaid
sequenceDiagram
    participant User
    participant Agent as AI Agent<br/>(Platform)
    participant CP as Credential<br/>Provider :8002
    participant Business as Business<br/>:8001
    participant PSP as PSP<br/>:8003

    User->>Agent: "Yes, go ahead"
    Agent->>CP: POST /tokens<br/>{"amount": 209.98, "currency": "USD"}
    CP-->>Agent: {"token": "tok_abc123...", "type": "PAYMENT_GATEWAY"}

    Agent->>Business: MCP tool call: complete_checkout(<br/>session_id, payment_token="tok_abc123...")

    Note over Business,PSP: Business authorizes payment via PSP
    Business->>PSP: POST /authorize<br/>{"token": "tok_abc123...", "amount": 209.98}
    PSP-->>Business: {"authorization_id": "auth_...", "status": "approved"}

    Business-->>Agent: {status: "completed", order_id: "order_xyz789"}
    Agent->>User: "Order confirmed! Order ID: order_xyz789"
```

### Full End-to-End Flow

```mermaid
sequenceDiagram
    participant User
    participant Agent as AI Agent (Platform)
    participant Business as Business :8001
    participant CP as Credential Provider :8002
    participant PSP as PSP :8003

    Note over User,PSP: 1. MCP Tool Discovery
    Agent->>Business: MCP initialize + tools/list
    Business-->>Agent: [browse_products, create_checkout,<br/>update_checkout, complete_checkout]

    Note over User,PSP: 2. Product Browsing
    User->>Agent: "What's available?"
    Agent->>Business: MCP: browse_products()
    Business-->>Agent: Product catalog
    Agent->>User: Product listing

    Note over User,PSP: 3. Checkout Creation
    User->>Agent: "Buy headphones + keyboard"
    Agent->>Business: MCP: create_checkout(items)
    Business-->>Agent: Session (incomplete)
    Agent->>User: "Total: $209.98. Need shipping info."

    Note over User,PSP: 4. Session Update
    User->>Agent: Name, email, address
    Agent->>Business: MCP: update_checkout(session_id, ...)
    Business-->>Agent: Session (ready_for_complete)
    Agent->>User: "Ready to pay?"

    Note over User,PSP: 5. Payment & Completion
    User->>Agent: "Yes"
    Agent->>CP: REST: POST /tokens
    CP-->>Agent: Payment token
    Agent->>Business: MCP: complete_checkout(session_id, token)
    Business->>PSP: POST /authorize
    PSP-->>Business: Approved
    Business-->>Agent: Session (completed) + order_id
    Agent->>User: "Order confirmed!"
```

## API Reference

### Business Service (`:8001`)

**MCP Endpoint** (`/mcp/`) -- auto-discovered tools:

| Tool | Description |
|------|-------------|
| `browse_products` | List all products in the catalog |
| `get_product_details` | Get details for a specific product by ID |
| `create_checkout` | Create a checkout session with selected items |
| `update_checkout` | Add buyer info and shipping address to a session |
| `complete_checkout` | Finalize purchase with a payment token |

**REST Endpoints** (also available):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/.well-known/ucp` | UCP discovery document (includes MCP endpoint URL) |
| `GET` | `/products` | List all products |
| `GET` | `/products/{id}` | Get single product |
| `POST` | `/checkout-sessions` | Create checkout session |
| `GET` | `/checkout-sessions/{id}` | Get session state |
| `PUT` | `/checkout-sessions/{id}` | Update buyer/fulfillment info |
| `POST` | `/checkout-sessions/{id}/complete` | Complete with payment |

### Credential Provider (`:8002`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/tokens` | Issue a tokenized payment credential |

### PSP (`:8003`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/authorize` | Authorize a payment token |

## Checkout Session Lifecycle

```
incomplete ──▶ ready_for_complete ──▶ completed
   │                                       │
   │  (buyer + fulfillment added)          │  (payment authorized)
   │                                       │
   └──────────── canceled ◀────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend | Next.js 16, React 19, Vercel AI SDK v6, Tailwind CSS |
| AI Model | Claude Sonnet via Anthropic API |
| Backend services | Python 3.12, FastAPI, Pydantic v2 |
| Dependency management | uv (Python), npm (Node.js) |
| Containerization | Docker, Docker Compose |

## UCP Spec Compliance

This demo implements both the [UCP REST](https://ucp.dev/latest/specification/overview/) and [UCP MCP](https://ucp.dev/latest/specification/checkout-mcp/) transport bindings:

- **Discovery**: `/.well-known/ucp` endpoint with capabilities, payment handlers, and MCP endpoint URL
- **MCP transport**: Business service exposes checkout capabilities as MCP tools, auto-discoverable by AI agents
- **REST transport**: Full checkout session lifecycle (create, read, update, complete)
- **Capability ID**: `dev.ucp.shopping.checkout` (version `2026-01-11`)
- **Payment handling**: Tokenized credentials via a separate Credential Provider, authorized through a PSP

The Business, Credential Provider, and PSP are intentionally simple (in-memory storage, simulated approvals) to focus on demonstrating the protocol flow rather than production infrastructure.
