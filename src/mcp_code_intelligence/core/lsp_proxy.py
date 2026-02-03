"""Generic LSP <-> MCP proxy manager.

Starts LSP binaries described in .mcp/mcp.json -> languageLsps and proxies MCP tool
requests (e.g., cpp_goto_definition) to LSP JSON-RPC methods.

This is a minimal, robust implementation focused on request/response mapping and
clean shutdown. It uses asyncio subprocesses and reads/writes the LSP Content-Length
framing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class _LSPProcess:
    def __init__(self, name: str, command: str, args: list[str], cwd: Path | None = None):
        self.name = name
        self.command = command
        self.args = args
        self.cwd = cwd
        self.proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._id_counter = 0
        self._pending: Dict[int, asyncio.Future] = {}

    async def start(self) -> None:
        cmd = [self.command] + list(self.args)
        logger.info(f"Starting LSP process {self.name}: {cmd}")
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.cwd) if self.cwd else None,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())
        # Perform LSP initialize handshake so language servers that require it
        # are ready to accept requests. If initialize fails, stop the process
        # and raise so the manager can skip registering this LSP.
        try:
            root_uri = None
            try:
                root_uri = (self.cwd.resolve()).as_uri() if self.cwd else Path.cwd().resolve().as_uri()
            except Exception:
                root_uri = None

            init_params = {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "capabilities": {},
                "workspaceFolders": None,
            }

            # Send initialize request and wait for a response
            resp = await self.send_request("initialize", init_params)
            logger.info(f"LSP {self.name} initialize response: {resp}")

            # Send initialized notification (no response expected)
            try:
                await self.send_notification("initialized", {})
            except Exception:
                # Non-fatal: continue even if notification fails
                logger.debug(f"Failed to send 'initialized' notification to {self.name}")
        except Exception as e:
            # Cleanup on failure to initialize
            logger.warning(f"LSP {self.name} failed initialize: {e}")
            try:
                await self.stop()
            except Exception:
                pass
            raise

    async def _read_stderr(self) -> None:
        if not self.proc or not self.proc.stderr:
            return
        try:
            while True:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                logger.debug(f"[{self.name} stderr] {line.decode().rstrip()}")
        except Exception as e:
            logger.debug(f"Error reading stderr for {self.name}: {e}")

    async def _read_stdout(self) -> None:
        if not self.proc or not self.proc.stdout:
            return
        reader = self.proc.stdout
        try:
            while True:
                # Read headers
                headers = {}
                # Read header lines until empty line
                while True:
                    line = await reader.readline()
                    if not line:
                        return
                    s = line.decode("utf-8", errors="ignore").strip()
                    if s == "":
                        break
                    if ":" in s:
                        k, v = s.split(":", 1)
                        headers[k.strip().lower()] = v.strip()

                length = int(headers.get("content-length", "0"))
                if length <= 0:
                    continue
                body = await reader.readexactly(length)
                try:
                    msg = json.loads(body.decode("utf-8", errors="ignore"))
                except Exception as e:
                    logger.debug(f"Failed to parse LSP message for {self.name}: {e}")
                    continue

                # Handle responses with id
                if isinstance(msg, dict) and "id" in msg:
                    req_id = msg.get("id")
                    if isinstance(req_id, int) and req_id in self._pending:
                        fut = self._pending.pop(req_id)
                        if not fut.cancelled():
                            fut.set_result(msg)
                # Notifications and other messages are ignored for now
        except asyncio.IncompleteReadError:
            logger.info(f"LSP process {self.name} stdout closed")
        except Exception as e:
            logger.exception(f"Error reading stdout for {self.name}: {e}")

    async def send_request(self, method: str, params: Any) -> Any:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("LSP process not running")

        self._id_counter += 1
        req_id = self._id_counter
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        body = json.dumps(payload, separators=(',', ':')).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut

        try:
            # type: ignore[attr-defined]
            self.proc.stdin.write(header + body)
            # type: ignore[attr-defined]
            await self.proc.stdin.drain()
        except Exception:
            self._pending.pop(req_id, None)
            raise

        # Wait for response or timeout
        try:
            res = await asyncio.wait_for(fut, timeout=15.0)
            return res
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise

    async def stop(self) -> None:
        try:
            if self.proc:
                logger.info(f"Stopping LSP process {self.name}")
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.info(f"Killing LSP process {self.name}")
                    self.proc.kill()
        except Exception:
            pass
        if self._reader_task:
            self._reader_task.cancel()

    async def send_notification(self, method: str, params: Any | None = None) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("LSP process not running")

        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")

        try:
            # type: ignore[attr-defined]
            self.proc.stdin.write(header + body)
            # type: ignore[attr-defined]
            await self.proc.stdin.drain()
        except Exception:
            raise


class LSPManager:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self._processes: Dict[str, _LSPProcess] = {}

    def _load_config(self) -> Dict[str, Dict[str, Any]]:
        cfg_path = self.project_root / ".mcp" / "mcp.json"
        if not cfg_path.exists():
            return {}
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg = data.get("languageLsps", {})
            if isinstance(cfg, list):
                logger.warning("languageLsps in mcp.json is a list, expected dict. Ignoring.")
                return {}
            return cfg or {}
        except Exception:
            return {}

    async def start_all(self) -> None:
        cfg = self._load_config()
        for lang_id, entry in cfg.items():
            cmd = entry.get("command")
            args = entry.get("args", []) or []
            if not cmd:
                continue
            # Avoid duplicate
            if lang_id in self._processes:
                continue
            proc = _LSPProcess(lang_id, cmd, args, cwd=self.project_root)
            try:
                await proc.start()
                self._processes[lang_id] = proc
            except Exception as e:
                logger.warning(f"Failed to start LSP {lang_id}: {e}")

    async def stop_all(self) -> None:
        procs = list(self._processes.values())
        for p in procs:
            try:
                await p.stop()
            except Exception:
                pass
        self._processes.clear()

    def is_available(self, lang_id: str) -> bool:
        return lang_id in self._processes

    async def request(self, lang_id: str, method: str, params: Any) -> Any:
        if lang_id not in self._processes:
            raise RuntimeError(f"LSP server for {lang_id} is not running")
        proc = self._processes[lang_id]
        return await proc.send_request(method, params)


# Module-level manager cache
_MANAGERS: Dict[str, LSPManager] = {}

def get_manager(project_root: Path) -> LSPManager:
    key = str(Path(project_root).resolve())
    if key not in _MANAGERS:
        _MANAGERS[key] = LSPManager(Path(project_root))
    return _MANAGERS[key]

async def start_proxies(project_root: Path) -> None:
    m = get_manager(project_root)
    await m.start_all()

async def stop_proxies(project_root: Path) -> None:
    key = str(Path(project_root).resolve())
    m = _MANAGERS.get(key)
    if m:
        await m.stop_all()
        del _MANAGERS[key]
