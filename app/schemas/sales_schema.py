from pydantic import BaseModel
from typing import List
from datetime import datetime


class SalesItemSchema(BaseModel):

    id: str
    product_id: int
    qty: float
    price: float
    subtotal: float


class SalesSchema(BaseModel):

    id: str
    invoice_number: str
    trx_date: datetime
    total: float
    items: List[SalesItemSchema]


class SyncRequestSchema(BaseModel):

    outlet: str
    sales: List[SalesSchema]