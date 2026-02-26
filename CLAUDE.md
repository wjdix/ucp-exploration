# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
# Start all backend services (Business :8001, Credential Provider :8002, PSP :8003)
docker compose up --build

# Rebuild a single service after code changes
docker build --network=host -t ucp-example-business services/business
docker compose up -d business

# Start frontend (requires ANTHROPIC_API_KEY in frontend/.env.local)
cd frontend && npm install && npm run dev

# Build frontend for production
cd frontend && npm run build

# Test backend health
curl localhost:8001/health && curl localhost:8002/health && curl localhost:8003/health

# Test MCP tool discovery
curl -X POST http://localhost:8001/mcp/ \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# Test full checkout flow via curl
curl -X POST localhost:8001/checkout-sessions -H "Content-Type: application/json" \
  -d '{"line_items":[{"product_id":"prod_001","quantity":1}]}'
```

## Architecture

This implements the [Universal Commerce Protocol (UCP)](https://ucp.dev/) with four participants:

- **Frontend** (Next.js 16 + Vercel AI SDK v6) — AI agent that auto-discovers merchant tools via MCP, orchestrates the purchase flow. Only the Credential Provider tool is hardcoded in `lib/tools.ts`; all merchant tools come from MCP discovery at runtime.
- **Business** (Python/FastAPI at :8001) — Merchant service with dual interfaces: MCP server at `/mcp/` for AI agent tool discovery, and REST API for checkout sessions. Calls PSP internally during payment completion.
- **Credential Provider** (Python/FastAPI at :8002) — Issues tokenized payment credentials. Separate UCP participant, called directly by the frontend via REST.
- **PSP** (Python/FastAPI at :8003) — Authorizes payment tokens. Only called by the Business service, never by the frontend.

### Communication Flow

```
Frontend --MCP--> Business /mcp/ (browse_products, create_checkout, update_checkout, complete_checkout)
Frontend --REST--> Credential Provider /tokens (get payment token)
Business --REST--> PSP /authorize (authorize payment during complete_checkout)
```

### Docker Networking

Services communicate internally via Docker network names (`http://psp:8000`). The `PSP_URL` env var on the Business service defaults to `http://psp:8000`. Frontend calls services on `localhost:{8001,8002}` (mapped ports).

## Key Implementation Details

**AI SDK v6 API**: Uses `inputSchema` (not `parameters`), `stopWhen: stepCountIs(8)` (not `maxSteps`), `toUIMessageStreamResponse()` (not `toDataStreamResponse`), and `sendMessage` (not `handleSubmit`) in the chat hook.

**MCP Server**: Business service uses `FastMCP` with `stateless_http=True`, `streamable_http_path="/"`, mounted at `/mcp` in FastAPI. The trailing slash matters — MCP endpoint is `/mcp/`.

**Checkout Session Lifecycle**: `incomplete` → `ready_for_complete` (when both buyer and fulfillment are set) → `completed` (after PSP authorization).

**In-memory state**: All services use Python dicts for storage. No persistence across restarts.

## Environment Variables

| Variable | Location | Default |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | `frontend/.env.local` | (required) |
| `BUSINESS_MCP_URL` | `frontend/.env.local` | `http://localhost:8001/mcp/` |
| `CREDENTIAL_PROVIDER_URL` | `frontend/.env.local` | `http://localhost:8002` |
| `PSP_URL` | `docker-compose.yml` | `http://psp:8000` |
