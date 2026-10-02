import json
import sys
from datetime import date
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from beaconforge import services
from beaconforge.config import Settings
from beaconforge.database import Database, Project
from beaconforge.schemas import Coverage, Event

SOURCE_CONTRACT = Path(__file__).resolve().parents[2] / "api" / "openapi.json"
CONTRACT_PATH = (
    SOURCE_CONTRACT
    if SOURCE_CONTRACT.is_file()
    else Path(sys.prefix) / "share" / "beaconforge" / "openapi.json"
)


def problem_response(status: int, title: str, detail: str, path: str) -> JSONResponse:
    return JSONResponse(
        {
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": path,
        },
        status_code=status,
        media_type="application/problem+json",
    )


class ContractApp(FastAPI):
    def openapi(self) -> dict[str, Any]:
        document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("OpenAPI contract must be an object")
        return document


class PayloadLimit:
    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT"):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                response = problem_response(
                    413, "Payload too large", "Maximum request size is 64 KiB", scope["path"]
                )
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay_body() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_body, send)


def create_app(database: Database, settings: Settings) -> FastAPI:
    app = ContractApp(title="BeaconForge", version="0.1.0")
    app.add_middleware(PayloadLimit, limit=settings.payload_limit)

    @app.exception_handler(services.Problem)
    async def handle_problem(request: Request, error: services.Problem) -> JSONResponse:
        return problem_response(error.status, error.title, error.detail, request.url.path)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, error: RequestValidationError) -> JSONResponse:
        return problem_response(
            422, "Invalid request", "Request parameters do not match the contract", request.url.path
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database(request: Request, error: SQLAlchemyError) -> JSONResponse:
        return problem_response(
            503, "Unavailable", "Database operation could not be completed", request.url.path
        )

    @app.exception_handler(HTTPException)
    async def handle_http(request: Request, error: HTTPException) -> JSONResponse:
        return problem_response(
            error.status_code, "Request failed", str(error.detail), request.url.path
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, error: Exception) -> JSONResponse:
        return problem_response(500, "Internal error", "Unexpected server error", request.url.path)

    def project(key: Annotated[str | None, Header(alias="X-Project-Key")] = None) -> Project:
        return services.authenticate(database, key)

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        with database.sessions() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.post("/v1/events", status_code=202)
    async def accept_event(
        request: Request,
        tenant: Annotated[Project, Depends(project)],
        delivery: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)],
        signature: Annotated[str, Header(alias="X-BeaconForge-Signature")],
    ) -> dict[str, Any]:
        body = await request.body()
        services.verify_signature(tenant.signing_secret, body, signature)
        try:
            event = Event.model_validate_json(body)
        except ValidationError:
            raise services.Problem(
                422, "Invalid event", "Event data does not match the contract"
            ) from None
        return await run_in_threadpool(services.accept, database, tenant, delivery, event)

    @app.get("/v1/events")
    def events(
        tenant: Annotated[Project, Depends(project)],
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, Any]:
        return services.list_events(database, tenant, limit, cursor)

    @app.post("/v1/events/{event_id}/replay", status_code=202)
    def replay(event_id: UUID, tenant: Annotated[Project, Depends(project)]) -> dict[str, Any]:
        return services.replay(database, tenant, str(event_id))

    @app.put("/v1/coverage", status_code=204)
    def coverage(body: Coverage, tenant: Annotated[Project, Depends(project)]) -> None:
        services.set_coverage(database, tenant, body)

    @app.get("/v1/metrics")
    def metrics(
        start: date, end: date, tenant: Annotated[Project, Depends(project)]
    ) -> dict[str, Any]:
        return services.metrics(database, tenant, start, end)

    return app


def application() -> FastAPI:
    settings = Settings()
    return create_app(Database(settings.database_url.get_secret_value()), settings)
