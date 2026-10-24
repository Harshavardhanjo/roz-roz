from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import admin, audit, helpers, households, ledger, requests, signups, tools
from .voice import whatsapp_webhook

app = FastAPI(title="Roz Roz API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (households.router, helpers.router, requests.router, ledger.router, audit.router,
          signups.router, admin.router, tools.router, whatsapp_webhook.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"ok": True, "stubs": settings.use_stubs}
