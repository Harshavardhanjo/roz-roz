from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import errors
from .config import settings
from .voice import whatsapp_webhook


def create_app(use_stubs: bool | None = None) -> FastAPI:
    stubs = settings.use_stubs if use_stubs is None else use_stubs

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler = None
        if not stubs and settings.enable_scheduler:
            from .services import scheduler as payday

            scheduler = payday.start()
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Roz Roz API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.web_origins, allow_methods=["*"], allow_headers=["*"])
    errors.install(app)

    if stubs:
        from . import stub_api

        app.include_router(stub_api.router)
        app.include_router(stub_api.tools_router)
    else:
        from .routers import admin, audit, helpers, households, ledger, requests, signups, tools

        for module in (households, helpers, requests, ledger, audit, signups, admin, tools):
            app.include_router(module.router)
    app.include_router(whatsapp_webhook.router)

    @app.get("/health")
    def health():
        return {"ok": True, "stubs": stubs}

    return app


app = create_app()
