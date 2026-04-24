
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.services.sales_service import SalesService
from app.utils.logger import logger
from app.services.rabbitmq import RabbitMQClient
from app.schemas.sales_event import PublishSalesRequest

router = APIRouter(prefix="/api/sales", tags=["Sales"])


def get_rabbitmq_client():
    return RabbitMQClient()

@router.get("/")
def get_sales(
    outlet: str = None,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db)
):
    try:
        result = SalesService.get_sales(
            db=db,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date
        )

        return {
            "success": True,
            "data": result
        }

    except Exception as e:
        logger.error(f"GET SALES ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch sales")


@router.get("/colorplate")
def get_sales_colorplate(
    outlet: str = None,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db)
):
    try:
        outlet = Request.state.outlet_code
         
        result = SalesService.get_sales_colorplate(
            db=db,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date
        )

        return {
            "success": True,
            "data": result
        }

    except Exception as e:
        logger.error(f"GET COLORPLATE SALES ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch colorplate sales")

@router.post("/publish")
def publish_sales(
    request: Request,
    body: PublishSalesRequest,
    db: Session = Depends(get_db), 
    rabbitmq_client: RabbitMQClient = Depends(get_rabbitmq_client)
):
    try:
        outlet = request.state.outlet_code

        sales = SalesService.get_sales_colorplate(
            db=db,
            outlet=outlet,
            start_date=body.date,
            end_date=body.date
        ) 
            
        if not sales:
            return {
                "success": True,
                "message": "No sales data to publish",
                "outlet": outlet,
                "date": body.date
            }
        
        logger.info(f"[PUBLISH] outlet={outlet} date={body.date} total={len(sales)}")

        total = 0 
        for sale in sales:
            payload = {
                "platecolor": sale.product_name,
                "outlet": sale.outlet_code,
                "date": sale.sale_date.strftime("%Y-%m-%d"),
                "sold": int(sale.sold)
            }

            event = {
                "event": body.routing_key,
                "data": payload,
                "meta": {
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "sync-sales-service",
                    "version": "1.0"
                }
            }
 
            logger.info(f"EVENT TO PUBLISH: {json.dumps(event)}")

            rabbitmq_client.publish(
                exchange=body.exchange,
                routing_key=body.routing_key,
                payload=event
            )
            total += 1

        return {
            "success": True,
            "message": f"{total} event(s) published",
            "outlet": outlet,
            "date": body.date
         }

    except Exception as e:
        logger.error(f"[RABBITMQ][PUBLISH_ERROR] {str(e)}", exc_info=True)

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to publish sales data",
                "error": str(e)
            }
        )