from fastapi import APIRouter

from app.services import report_service as svc

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("")
def list_reports():
    return svc.list_reports()


@router.post("/freeze")
def freeze():
    return svc.freeze_report()


@router.get("/{report_id}")
def get_report(report_id: int):
    return svc.get_report(report_id)


@router.post("/{report_id}/rematerialize")
def rematerialize(report_id: int):
    return svc.rematerialize(report_id)
