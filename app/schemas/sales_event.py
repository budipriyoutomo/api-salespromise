from datetime import date

from pydantic import BaseModel


class PublishSalesRequest(BaseModel):
    exchange: str = "posdata_exchange"
    routing_key: str = "posdata.created"
    date: date
