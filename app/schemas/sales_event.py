from pydantic import BaseModel
from datetime import date

class PublishSalesRequest(BaseModel):
    exchange: str = "posdata_exchange"
    routing_key: str = "posdata.created"
    date: date