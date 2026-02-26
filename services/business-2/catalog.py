PRODUCTS: dict[str, dict] = {
    "prod_b001": {
        "id": "prod_b001",
        "title": "The Pragmatic Programmer",
        "description": "A classic guide to software craftsmanship covering practical approaches to software development.",
        "price": 44.99,
        "currency": "USD",
        "image_url": "https://placehold.co/400x400?text=Pragmatic+Programmer",
    },
    "prod_b002": {
        "id": "prod_b002",
        "title": "Designing Data-Intensive Applications",
        "description": "An in-depth exploration of the principles and practicalities of data systems and how to build reliable, scalable applications.",
        "price": 39.99,
        "currency": "USD",
        "image_url": "https://placehold.co/400x400?text=DDIA",
    },
    "prod_b003": {
        "id": "prod_b003",
        "title": "Structure and Interpretation of Computer Programs",
        "description": "A foundational computer science textbook covering abstraction, recursion, interpreters, and metalinguistic abstraction.",
        "price": 29.99,
        "currency": "USD",
        "image_url": "https://placehold.co/400x400?text=SICP",
    },
    "prod_b004": {
        "id": "prod_b004",
        "title": "Clean Code",
        "description": "A handbook of agile software craftsmanship with practical advice on writing readable, maintainable code.",
        "price": 34.99,
        "currency": "USD",
        "image_url": "https://placehold.co/400x400?text=Clean+Code",
    },
}


def get_product(product_id: str) -> dict | None:
    return PRODUCTS.get(product_id)


def list_products() -> list[dict]:
    return list(PRODUCTS.values())
