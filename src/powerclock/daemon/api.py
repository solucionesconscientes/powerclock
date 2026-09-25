"""Local HTTP + WebSocket API (docs/ARCHITECTURE.md §8): 127.0.0.1 only, bearer token."""

import asyncio
import contextlib
import secrets
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocketDisconnect

from powerclock import __version__
from powerclock.daemon.core import DaemonError, PostponeRequest, QuickRequest, WakeRequest
from powerclock.doctor import capabilities
from powerclock.models import rule_json_schema

if TYPE_CHECKING:
    from powerclock.daemon.core import Daemon


def create_app(daemon: "Daemon") -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await daemon.start()
        try:
            yield
        finally:
            await daemon.stop()

    app = FastAPI(
        title="powerclock",
        version=__version__,
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    def token_ok(connection: HTTPConnection, allow_query: bool = False) -> bool:
        scheme, _, token = connection.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" and allow_query:
            token = connection.query_params.get("token", "")
        elif scheme.lower() != "bearer":
            token = ""
        return bool(token) and secrets.compare_digest(token, daemon.token)

    async def authorize(request: Request) -> None:  # async: no worker thread per request
        if not token_ok(request):
            raise HTTPException(401, "invalid or missing token", {"WWW-Authenticate": "Bearer"})

    @app.exception_handler(DaemonError)
    async def daemon_error(request: Request, exc: DaemonError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    # Every route is async so that it runs in the daemon's event loop, next to the engine.
    api = APIRouter(dependencies=[Depends(authorize)])
    JsonBody = Annotated[dict[str, Any], Body()]

    @api.get("/health")
    async def health() -> dict[str, Any]:
        return daemon.health()

    @api.get("/rules")
    async def list_rules() -> list[dict[str, Any]]:
        return [rule.model_dump(mode="json") for rule in daemon.list_rules()]

    @api.post("/rules", status_code=201)
    async def create_rule(body: JsonBody) -> dict[str, Any]:
        return daemon.create_rule(body).model_dump(mode="json")

    @api.get("/rules/{rule_id}")
    async def get_rule(rule_id: str) -> dict[str, Any]:
        return daemon.get_rule(rule_id).model_dump(mode="json")

    @api.put("/rules/{rule_id}")
    async def replace_rule(rule_id: str, body: JsonBody) -> dict[str, Any]:
        return daemon.replace_rule(rule_id, body).model_dump(mode="json")

    @api.delete("/rules/{rule_id}", status_code=204)
    async def delete_rule(rule_id: str) -> Response:
        daemon.delete_rule(rule_id)
        return Response(status_code=204)

    @api.post("/rules/{rule_id}/enable")
    async def enable_rule(rule_id: str) -> dict[str, Any]:
        return daemon.set_enabled(rule_id, True).model_dump(mode="json")

    @api.post("/rules/{rule_id}/disable")
    async def disable_rule(rule_id: str) -> dict[str, Any]:
        return daemon.set_enabled(rule_id, False).model_dump(mode="json")

    @api.post("/rules/{rule_id}/run", status_code=202)
    async def run_rule(rule_id: str) -> dict[str, Any]:
        return daemon.run_rule(rule_id).model_dump(mode="json")

    @api.post("/rules/{rule_id}/cancel")
    async def cancel_rule(rule_id: str) -> dict[str, Any]:
        return daemon.cancel_rule(rule_id)

    @api.post("/rules/{rule_id}/postpone")
    async def postpone_rule(rule_id: str, request: PostponeRequest | None = None) -> dict[str, Any]:
        return daemon.postpone_rule(rule_id, (request or PostponeRequest()).delay)

    @api.post("/quick", status_code=201)
    async def quick(request: QuickRequest) -> dict[str, Any]:
        return daemon.quick(request).model_dump(mode="json")

    @api.post("/wake", status_code=201)
    async def wake(request: WakeRequest) -> dict[str, Any]:
        return daemon.wake(request).model_dump(mode="json")

    @api.get("/pending")
    async def pending() -> dict[str, Any]:
        return daemon.pending()

    @api.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        return daemon.get_run(run_id).model_dump(mode="json")

    @api.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        return daemon.cancel_run(run_id)

    @api.post("/cancel")
    async def cancel_current() -> dict[str, Any]:
        return daemon.cancel_current()

    @api.post("/runs/{run_id}/postpone")
    async def postpone_run(run_id: str, request: PostponeRequest | None = None) -> dict[str, Any]:
        return daemon.postpone_run(run_id, (request or PostponeRequest()).delay)

    @api.post("/postpone")
    async def postpone_current(request: PostponeRequest | None = None) -> dict[str, Any]:
        return daemon.postpone_current((request or PostponeRequest()).delay)

    @api.get("/history")
    async def history(
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        rule_id: str | None = None,
    ) -> dict[str, Any]:
        runs = daemon.history.list(limit, offset, rule_id)
        return {
            "total": daemon.history.count(rule_id),
            "runs": [run.model_dump(mode="json") for run in runs],
        }

    @api.get("/capabilities")
    async def get_capabilities() -> list[dict[str, Any]]:
        return [row.model_dump() for row in await capabilities(daemon.backend)]

    @api.get("/apps")
    async def installed_apps() -> list[dict[str, Any]]:
        return await daemon.apps()

    @api.get("/recipes")
    async def list_recipes() -> list[dict[str, Any]]:
        return daemon.list_recipes()

    @api.put("/settings/tariff")
    async def put_tariff(body: JsonBody) -> dict[str, Any]:
        return daemon.set_tariff(body.get("tariff"))

    @api.get("/schema/rule")
    async def schema() -> dict[str, Any]:
        return rule_json_schema()

    app.include_router(api)

    @app.websocket("/events")
    async def events(websocket: WebSocket) -> None:
        # Header or ?token=…: some WebSocket clients cannot set headers.
        if not token_ok(websocket, allow_query=True):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        with daemon.hub.subscribe() as queue:
            receiver = asyncio.ensure_future(websocket.receive_text())
            try:
                while True:
                    getter = asyncio.ensure_future(queue.get())
                    done, _ = await asyncio.wait(
                        {getter, receiver}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if receiver in done:
                        getter.cancel()
                        receiver.result()  # raises WebSocketDisconnect when the client left
                        receiver = asyncio.ensure_future(websocket.receive_text())
                        continue
                    await websocket.send_json(getter.result().model_dump(mode="json"))
            except WebSocketDisconnect:
                pass
            finally:
                receiver.cancel()

    return app
