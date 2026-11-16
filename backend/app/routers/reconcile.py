from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services import reconcile_service as svc

router = APIRouter(prefix="/reconcile", tags=["reconcile"])


class ConfigIn(BaseModel):
    window_mode: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    rel_start_hours: float | None = None
    rel_end_hours: float | None = None
    outside_policy: str | None = None
    mismatch_policy: str | None = None


class ResolveIn(BaseModel):
    note: str | None = None


@router.get("/config")
def get_config():
    return svc.get_config()


@router.put("/config")
def update_config(body: ConfigIn):
    return svc.update_config(body.model_dump(exclude_unset=True))


@router.post("/run")
def run_reconcile():
    return svc.run_reconcile()


@router.get("/reports")
def list_reports():
    return svc.list_reports()


@router.get("/reports/{report_id}")
def get_report(report_id: int):
    return svc.get_report(report_id)


@router.get("/flags")
def list_flags(status: str | None = Query(default=None)):
    return svc.list_flags(status)


@router.post("/flags/{flag_id}/resolve")
def resolve_flag(flag_id: int, body: ResolveIn):
    return svc.resolve_flag(flag_id, body.note)
