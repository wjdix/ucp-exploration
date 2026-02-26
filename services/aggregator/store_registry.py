import os
import json
from dataclasses import dataclass


@dataclass
class StoreConfig:
    store_id: str
    name: str
    mcp_url: str


def load_stores() -> list[StoreConfig]:
    raw = os.environ.get("STORES", "[]")
    return [StoreConfig(**s) for s in json.loads(raw)]
