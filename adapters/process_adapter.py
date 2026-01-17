from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable, Dict, List, Optional


class ProcessAdapter:
    def __init__(self) -> None:
        self.proc: Optional[asyncio.subprocess.Process] = None

    async def start(
        self,
        cmd: List[str],
        workdir: str,
        env: Dict[str, str],
        on_line: Callable[[str], Awaitable[None]],
    ) -> None:
        if self.proc and self.proc.returncode is None:
            raise RuntimeError("process already running")

        thing = os.environ.copy()
        thing.update(env)

        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workdir,
            env=thing,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        asyncio.create_task(self._read_stdout(on_line))

    async def _read_stdout(self, on_line: Callable[[str], Awaitable[None]]) -> None:
        if not self.proc or not self.proc.stdout:
            return

        while True:
            thing = await self.proc.stdout.readline()
            if not thing:
                break
            line = thing.decode("utf-8", errors="replace").rstrip("\n")
            await on_line(line)

    async def stop(self) -> None:
        if not self.proc or self.proc.returncode is not None:
            return
        self.proc.terminate()
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            self.proc.kill()
            await self.proc.wait()

    async def wait(self) -> int:
        if not self.proc:
            return 0
        return await self.proc.wait()

    def is_running(self) -> bool:
        return bool(self.proc and self.proc.returncode is None)

    def exit_code(self) -> Optional[int]:
        if not self.proc:
            return None
        return self.proc.returncode
