"""Key-only SSH tunnel for the manually started Runpod Pod."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from runpod_discovery import PodConnection


class TunnelError(RuntimeError):
    """The Pod cannot be reached through the configured SSH tunnel."""


class PodSSHTunnel:
    def __init__(
        self,
        *,
        key_path: str,
        user: str = "root",
        local_port: int = 18000,
        known_hosts_path: str = "/root/.ssh/known_hosts",
        strict_host_key_checking: str = "accept-new",
    ) -> None:
        self.key_path = Path(key_path)
        self.user = user
        self.local_port = local_port
        self.known_hosts_path = Path(known_hosts_path)
        self.strict_host_key_checking = strict_host_key_checking
        self.process: asyncio.subprocess.Process | None = None
        self.pod_id: str | None = None
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.local_port}"

    async def ensure(self, connection: PodConnection) -> str:
        async with self._lock:
            if (
                self.process is not None
                and self.process.returncode is None
                and self.pod_id == connection.pod_id
            ):
                return self.base_url
            await self._stop_locked()
            if connection.ssh_public_port is None:
                raise TunnelError("Pod has no mapped SSH port; expose 22/tcp in its template")
            if not self.key_path.is_file():
                raise TunnelError(f"SSH key is not mounted at {self.key_path}")
            self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
            args = [
                "ssh", "-N", "-T",
                "-L", f"127.0.0.1:{self.local_port}:127.0.0.1:{connection.internal_port}",
                "-p", str(connection.ssh_public_port),
                "-i", str(self.key_path),
                "-o", "BatchMode=yes",
                "-o", "IdentitiesOnly=yes",
                "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-o", f"StrictHostKeyChecking={self.strict_host_key_checking}",
                "-o", f"UserKnownHostsFile={self.known_hosts_path}",
                f"{self.user}@{connection.public_ip}",
            ]
            self.process = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            await asyncio.sleep(0.4)
            if self.process.returncode is not None:
                error = await self.process.stderr.read() if self.process.stderr else b""
                detail = error.decode("utf-8", "replace").strip()[-500:]
                raise TunnelError(f"SSH tunnel failed: {detail or 'process exited'}")
            self.pod_id = connection.pod_id
            return self.base_url

    async def close(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        if self.process is None:
            self.pod_id = None
            return
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None
        self.pod_id = None


def tunnel_from_environment() -> PodSSHTunnel:
    return PodSSHTunnel(
        key_path=os.getenv("POD_SSH_KEY_PATH", "/run/secrets/muse-pod-ssh-key"),
        user=os.getenv("POD_SSH_USER", "root"),
        local_port=int(os.getenv("POD_TUNNEL_PORT", "18000")),
        known_hosts_path=os.getenv("POD_SSH_KNOWN_HOSTS", "/root/.ssh/known_hosts"),
        strict_host_key_checking=os.getenv("POD_SSH_STRICT_HOST_KEY_CHECKING", "accept-new"),
    )
