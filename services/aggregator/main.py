import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mcp_tools import mcp, init_stores
from store_registry import load_stores


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_stores()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="UCP Store Aggregator", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/mcp", mcp.streamable_http_app())


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/stores")
async def list_stores_endpoint():
    stores = load_stores()
    return [{"store_id": s.store_id, "name": s.name, "mcp_url": s.mcp_url} for s in stores]
