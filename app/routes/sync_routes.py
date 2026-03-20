from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.sales_schema import SyncRequestSchema
from app.services.sales_service import SalesService
from app.utils.logger import logger


router = APIRouter(prefix="/api/sync", tags=["Sync"])


@router.post("/sales")
def sync_sales(payload: SyncRequestSchema, db: Session = Depends(get_db)):

    try:

        logger.info(
            f"SYNC REQUEST outlet={payload.outlet} sales_count={len(payload.sales)}"
        )

        inserted = SalesService.sync_sales(
            db=db,
            outlet=payload.outlet,
            sales_list=payload.sales
        )

        return {
            "success": True,
            "inserted": inserted
        }

    except Exception:

        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "message": "Database error"
            }
        )