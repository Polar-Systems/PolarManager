from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ServerStatus(str, Enum):
    stopped = "stopped"
    starting = "starting"
    running = "running"
    stopping = "stopping"
    crashed = "crashed"
    updating = "updating"
    degraded = "degraded"


class HealthState(str, Enum):
    ok = "ok"
    warn = "warn"
    fail = "fail"


class ServerConfig(BaseModel):
    id: str
    name: str
    workdir: str
    start_cmd: List[str]
    stop_cmd: Optional[List[str]] = None
    env: Dict[str, str] = Field(default_factory=dict)

    restart_policy: str = "on-failure"  # always | on-failure | never
    max_restart_per_minute: int = 6

    priority: int = 50

    health_port: Optional[int] = None
    health_http_url: Optional[str] = None
    health_timeout_s: float = 2.0

    log_important_keywords: List[str] = Field(
        default_factory=lambda: ["ERROR", "FATAL", "panic", "Exception"]
    )


class AdapterConfig(BaseModel):
    enabled: bool = False
    url: Optional[str] = None
    token: Optional[str] = None
    shared_secret: Optional[str] = None


class AppConfig(BaseModel):
    client_id: str = "client-1"

    http_bind: str = "127.0.0.1"
    http_port: int = 8765

    max_servers: int = 25

    polarsystems: AdapterConfig = Field(default_factory=AdapterConfig)
    polarbridge: AdapterConfig = Field(default_factory=AdapterConfig)
    polarscript: AdapterConfig = Field(default_factory=AdapterConfig)

    servers: List[ServerConfig] = Field(default_factory=list)


class Event(BaseModel):
    type: str
    ts: float
    server_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
