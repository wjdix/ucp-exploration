from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Product(BaseModel):
    id: str
    title: str
    description: str
    price: float
    currency: str = "USD"
    image_url: str


class LineItemRequest(BaseModel):
    product_id: str
    quantity: int = 1


class LineItem(BaseModel):
    product_id: str
    quantity: int
    item: Product
    totals: dict[str, float]


class Buyer(BaseModel):
    email: str
    first_name: str
    last_name: str


class PostalAddress(BaseModel):
    street_address: str
    address_locality: str
    address_region: str
    postal_code: str
    address_country: str


class FulfillmentDestination(BaseModel):
    type: str = "shipping"
    address: PostalAddress


class Fulfillment(BaseModel):
    destinations: list[FulfillmentDestination]


class PaymentCredential(BaseModel):
    type: str
    token: str


class PaymentInstrument(BaseModel):
    credential: PaymentCredential


class CheckoutSession(BaseModel):
    id: str
    status: str = "incomplete"
    line_items: list[LineItem] = Field(default_factory=list)
    buyer: Buyer | None = None
    fulfillment: Fulfillment | None = None
    totals: dict[str, float] = Field(default_factory=dict)
    payment: dict | None = None
    order_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreateCheckoutRequest(BaseModel):
    line_items: list[LineItemRequest]


class UpdateCheckoutRequest(BaseModel):
    buyer: Buyer | None = None
    fulfillment: Fulfillment | None = None


class CompleteCheckoutRequest(BaseModel):
    payment: PaymentInstrument
