from __future__ import annotations

import asyncio
import json
from pathlib import Path

import uvicorn

from polarmanager.core.logging_setup import setup_logging
from polarmanager.core.models import AppConfig
from polarmanager.core.manager import PolarManager
from polarmanager.app import build_app
from polarmanager.adapters.polarsystems_client import PolarSystemsClient


async def main_async() -> None:
    setup_logging()

    thing = json.loads(Path("config.json").read_text(encoding="utf-8"))
    cfg = AppConfig.model_validate(thing)

    manager = PolarManager(cfg)
    app = build_app(
        manager, cfg.polarscript.shared_secret or cfg.polarbridge.shared_secret
    )

    manager_task = asyncio.create_task(manager.loop())

    ws_task = None
    ws_client = None
    if cfg.polarsystems.enabled and cfg.polarsystems.url and cfg.polarsystems.token:
        ws_client = PolarSystemsClient(cfg.polarsystems.url, cfg.polarsystems.token)
        ws_task = asyncio.create_task(ws_client.loop(manager.event_q))

    await manager.start_all()

    server = uvicorn.Server(
        uvicorn.Config(app, host=cfg.http_bind, port=cfg.http_port, log_level="info")
    )
    await server.serve()

    manager.stop()
    if ws_client:
        ws_client.stop()

    await manager_task
    if ws_task:
        ws_task.cancel()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
