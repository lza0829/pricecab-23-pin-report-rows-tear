from fastapi import APIRouter
from pydantic import BaseModel

from app.services import apply_service as svc

router = APIRouter(prefix="/apply", tags=["apply"])


class ClockIn(BaseModel):
    business_clock: str


@router.get("/clock")
def get_clock():
    return svc.get_clock()


@router.put("/clock")
def set_clock(body: ClockIn):
    return svc.set_clock(body.business_clock)


@router.get("/batches")
def list_batches():
    return svc.list_batches()


@router.get("/rejections")
def list_rejections():
    return svc.list_rejections()


@router.post("/due")
def apply_due():
    return svc.apply_due()
