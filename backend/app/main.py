from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import PROJECT_NAME
from app.seed import seed_if_empty
from app.routers import dashboard, skus, tickets, apply, prices, reconcile, settings, reports

seed_if_empty()

app = FastAPI(title=PROJECT_NAME)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api")
app.include_router(skus.router, prefix="/api")
app.include_router(tickets.router, prefix="/api")
app.include_router(apply.router, prefix="/api")
app.include_router(prices.router, prefix="/api")
app.include_router(reconcile.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
