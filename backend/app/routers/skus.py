from fastapi import APIRouter

from app.services import catalog_service as catalog

router = APIRouter(prefix="/skus", tags=["skus"])


@router.get("")
def list_skus():
    return catalog.list_skus()
