from fastapi import APIRouter, Query

from app.services import reconcile_service as svc

router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("/book")
def price_book():
    return svc.list_price_book()


@router.get("/history")
def history(sku_code: str | None = Query(default=None)):
    return svc.list_history(sku_code)
