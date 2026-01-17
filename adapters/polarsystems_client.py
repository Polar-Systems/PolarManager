from __future__ import annotations

import asyncio
import json
import logging
import websockets

from polarmanager.core.models import Event

log = logging.getLogger("polarmanager.polarsystems")


class PolarSystemsClient:
    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def loop(self, event_q: "asyncio.Queue[Event]") -> None:
        headers = {"Authorization": f"Bearer {self.token}"}

        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.url, extra_headers=headers, ping_interval=20
                ) as ws:
                    log.info("connected")
                    await ws.send(json.dumps({"type": "hello"}))
                    await self._run_session(ws, event_q)
            except Exception:
                log.warning("disconnected, retrying")
                await asyncio.sleep(2.0)

    async def _run_session(self, ws, event_q: "asyncio.Queue[Event]") -> None:
        async def sender():
            while True:
                thing = await event_q.get()
                try:
                    await ws.send(thing.model_dump_json())
                finally:
                    event_q.task_done()

        send_task = asyncio.create_task(sender())
        try:
            while True:
                msg = await ws.recv()
                _ = msg
                # här kommer commands in senare
        finally:
            send_task.cancel()