PRODUCTS: dict[str, dict] = {
    "prod_001": {
        "id": "prod_001",
        "title": "Wireless Headphones",
        "description": "Premium over-ear wireless headphones with noise cancellation.",
        "price": 79.99,
        "currency": "USD",
        "image_url": "https://placehold.co/400x400?text=Headphones",
    },
    "prod_002": {
        "id": "prod_002",
        "title": "USB-C Hub",
        "description": "7-in-1 USB-C hub with HDMI, USB-A, SD card, and ethernet.",
        "price": 49.99,
        "currency": "USD",
        "image_url": "https://placehold.co/400x400?text=USB-C+Hub",
    },
    "prod_003": {
        "id": "prod_003",
        "title": "Mechanical Keyboard",
        "description": "Compact mechanical keyboard with tactile switches and RGB lighting.",
        "price": 129.99,
        "currency": "USD",
        "image_url": "https://placehold.co/400x400?text=Keyboard",
    },
    "prod_004": {
        "id": "prod_004",
        "title": "Laptop Stand",
        "description": "Adjustable aluminum laptop stand for improved ergonomics.",
        "price": 39.99,
        "currency": "USD",
        "image_url": "https://placehold.co/400x400?text=Laptop+Stand",
    },
}


def get_product(product_id: str) -> dict | None:
    return PRODUCTS.get(product_id)


def list_products() -> list[dict]:
    return list(PRODUCTS.values())
