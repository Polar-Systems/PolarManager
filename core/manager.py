from __future__ import annotations

import asyncio
import logging
import time
import socket
from typing import Dict, Optional

import aiohttp

from .models import AppConfig, Event, HealthState, ServerConfig, ServerStatus
from .process_adapter import ProcessAdapter

log = logging.getLogger("polarmanager.manager")


class ManagedServer:
    def __init__(self, cfg: ServerConfig, event_q: "asyncio.Queue[Event]") -> None:
        self.cfg = cfg
        self.event_q = event_q
        self.proc = ProcessAdapter()

        self.status: ServerStatus = ServerStatus.stopped
        self.health: HealthState = HealthState.ok

        self._restart_times: list[float] = []
        self._lock = asyncio.Lock()

    def _now(self) -> float:
        return time.time()

    async def _emit(self, type_: str, data: dict) -> None:
        await self.event_q.put(
            Event(type=type_, ts=self._now(), server_id=self.cfg.id, data=data)
        )

    def _allow_restart(self) -> bool:
        now = self._now()
        minute_ago = now - 60.0
        self._restart_times = [t for t in self._restart_times if t >= minute_ago]
        return len(self._restart_times) < self.cfg.max_restart_per_minute

    async def _on_log_line(self, line: str) -> None:
        await self._emit("log_line", {"line": line})

        for kw in self.cfg.log_important_keywords:
            if kw in line:
                await self._emit("important_log", {"line": line, "keyword": kw})
                break

    async def start(self, reason: str = "") -> None:
        async with self._lock:
            if self.proc.is_running():
                return
            self.status = ServerStatus.starting
            await self._emit("status", {"status": self.status.value, "reason": reason})

            await self.proc.start(
                self.cfg.start_cmd, self.cfg.workdir, self.cfg.env, self._on_log_line
            )

            self.status = ServerStatus.running
            await self._emit("status", {"status": self.status.value, "reason": reason})

    async def stop(self, reason: str = "") -> None:
        async with self._lock:
            if not self.proc.is_running():
                self.status = ServerStatus.stopped
                await self._emit(
                    "status", {"status": self.status.value, "reason": reason}
                )
                return

            self.status = ServerStatus.stopping
            await self._emit("status", {"status": self.status.value, "reason": reason})

            if self.cfg.stop_cmd:
                await self._emit("info", {"msg": "stop_cmd not implemented yet"})

            await self.proc.stop()
            self.status = ServerStatus.stopped
            await self._emit("status", {"status": self.status.value, "reason": reason})

    async def restart(self, reason: str = "") -> None:
        await self.stop(reason=reason)
        await asyncio.sleep(0.2)
        await self.start(reason=reason)

    async def tick_supervisor(self) -> None:
        if self.proc.is_running():
            return

        code = self.proc.exit_code()
        if code is None:
            return

        if code == 0:
            self.status = ServerStatus.stopped
            return

        self.status = ServerStatus.crashed
        await self._emit("crash", {"exit_code": code})

        if self.cfg.restart_policy == "never":
            return
        if not self._allow_restart():
            await self._emit("warn", {"msg": "restart rate limited"})
            return

        self._restart_times.append(self._now())
        await self.start(reason="auto_restart")

    async def tick_health(self) -> None:
        ok = True

        if self.cfg.health_port is not None:
            ok = ok and await _check_port_open(
                self.cfg.health_port, timeout_s=self.cfg.health_timeout_s
            )

        if self.cfg.health_http_url:
            ok = ok and await _check_http(
                self.cfg.health_http_url, timeout_s=self.cfg.health_timeout_s
            )

        new_state = HealthState.ok if ok else HealthState.fail
        if new_state != self.health:
            self.health = new_state
            await self._emit("health", {"health": self.health.value})


class PolarManager:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.event_q: "asyncio.Queue[Event]" = asyncio.Queue()
        self.servers: Dict[str, ManagedServer] = {}

        thing = cfg.servers[: cfg.max_servers]
        for otherThing in thing:
            self.servers[otherThing.id] = ManagedServer(otherThing, self.event_q)

        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict:
        return {
            "client_id": self.cfg.client_id,
            "servers": {
                sid: {
                    "name": s.cfg.name,
                    "status": s.status.value,
                    "health": s.health.value,
                    "priority": s.cfg.priority,
                }
                for sid, s in self.servers.items()
            },
        }

    async def start_all(self) -> None:
        for sid, s in self.servers.items():
            await s.start(reason="boot")

    async def loop(self) -> None:
        while not self._stop.is_set():
            for sid, s in self.servers.items():
                try:
                    await s.tick_supervisor()
                    await s.tick_health()
                except Exception:
                    log.exception("tick failed for %s", sid)
            await asyncio.sleep(1.0)

    async def do_action(self, server_id: str, action: str, reason: str = "") -> None:
        thing = self.servers.get(server_id)
        if not thing:
            raise KeyError("unknown server_id")

        if action == "start":
            await thing.start(reason=reason)
        elif action == "stop":
            await thing.stop(reason=reason)
        elif action == "restart":
            await thing.restart(reason=reason)
        else:
            raise ValueError("unknown action")


async def _check_port_open(
    port: int, host: str = "127.0.0.1", timeout_s: float = 1.0
) -> bool:
    loop = asyncio.get_running_loop()
    try:
        fut = loop.run_in_executor(None, _sync_port_check, host, port, timeout_s)
        return await asyncio.wait_for(fut, timeout=timeout_s + 0.2)
    except Exception:
        return False


def _sync_port_check(host: str, port: int, timeout_s: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout_s)
        return s.connect_ex((host, port)) == 0


async def _check_http(url: str, timeout_s: float) -> bool:
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                return 200 <= resp.status < 400
    except Exception:
        return False