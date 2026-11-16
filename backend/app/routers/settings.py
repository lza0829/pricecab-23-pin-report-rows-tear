from fastapi import APIRouter

from app.db import connect
from app.repositories import settings as settings_repo

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def list_settings():
    conn = connect()
    try:
        return settings_repo.list_all(conn)
    finally:
        conn.close()
