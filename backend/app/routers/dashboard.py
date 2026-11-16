from fastapi import APIRouter

from app.config import PROJECT, PROJECT_NAME
from app.services import catalog_service as catalog

router = APIRouter(tags=["dashboard"])


@router.get("/health")
def health():
    return {"ok": True, "project": PROJECT, "name": PROJECT_NAME}


@router.get("/dashboard")
def dashboard():
    return catalog.dashboard()
