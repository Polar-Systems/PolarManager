from __future__ import annotations

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from polarmanager.core.manager import PolarManager
from polarmanager.core.models import Event


class ActionReq(BaseModel):
    server_id: str
    reason: Optional[str] = ""


class PluginEventReq(BaseModel):
    server_id: Optional[str] = None
    type: str
    data: dict = {}


def build_app(manager: PolarManager, shared_secret: Optional[str]) -> FastAPI:
    app = FastAPI(title="PolarManager")

    @app.get("/v1/status")
    async def status():
        return manager.snapshot()

    @app.post("/v1/start")
    async def start(req: ActionReq):
        try:
            await manager.do_action(req.server_id, "start", reason=req.reason or "api")
        except KeyError:
            raise HTTPException(404, "unknown server_id")
        return {"ok": True}

    @app.post("/v1/stop")
    async def stop(req: ActionReq):
        try:
            await manager.do_action(req.server_id, "stop", reason=req.reason or "api")
        except KeyError:
            raise HTTPException(404, "unknown server_id")
        return {"ok": True}

    @app.post("/v1/restart")
    async def restart(req: ActionReq):
        try:
            await manager.do_action(
                req.server_id, "restart", reason=req.reason or "api"
            )
        except KeyError:
            raise HTTPException(404, "unknown server_id")
        return {"ok": True}

    @app.post("/v1/plugin/event")
    async def plugin_event(
        req: PluginEventReq,
        x_polar_secret: Optional[str] = Header(default=None),
    ):
        if shared_secret:
            if not x_polar_secret or x_polar_secret != shared_secret:
                raise HTTPException(401, "bad secret")

        thing = Event(
            type=req.type,
            ts=(
                manager.servers[next(iter(manager.servers))]._now()
                if manager.servers
                else 0.0
            ),
            server_id=req.server_id,
            data=req.data,
        )
        await manager.event_q.put(thing)
        return {"ok": True}

    return app