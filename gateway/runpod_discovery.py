"""Read-only discovery of the manually managed Muse Glimmer Pod."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class DiscoveryError(RuntimeError):
    """The Runpod API response cannot identify a safe Pod target."""


@dataclass(frozen=True)
class PodConnection:
    pod_id: str
    name: str
    desired_status: str
    public_ip: str
    internal_port: int
    public_port: int | None
    ssh_public_port: int | None
    base_url: str | None
    template_id: str | None
    network_volume_id: str | None
    gpu_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunpodPodDiscovery:
    """Discover exactly one running Pod without mutating Runpod resources."""

    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = "https://rest.runpod.io/v1",
        template_id: str,
        data_center_id: str,
        network_volume_id: str,
        internal_port: int = 8000,
        name_prefix: str = "",
        timeout_seconds: float = 5.0,
    ) -> None:
        if not api_key:
            raise ValueError("Runpod API key is required for read-only discovery")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.template_id = template_id
        self.data_center_id = data_center_id
        self.network_volume_id = network_volume_id
        self.internal_port = internal_port
        self.name_prefix = name_prefix
        self.timeout_seconds = timeout_seconds

    def _list_pods(self) -> list[dict[str, Any]]:
        query = urlencode(
            [
                ("computeType", "GPU"),
                ("dataCenterId", self.data_center_id),
                ("includeNetworkVolume", "true"),
            ]
        )
        request = Request(
            f"{self.api_base}/pods?{query}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except Exception as exc:  # urllib has several transport/error types.
            raise DiscoveryError(f"Runpod Pod discovery failed: {exc}") from exc
        # The v1 REST API currently returns an array. Keep accepting the
        # object-with-items shape as well so discovery remains compatible with
        # newer Runpod REST responses.
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
            items = payload["items"]
        else:
            raise DiscoveryError("Runpod Pod list response had no Pod items")
        return [item for item in items if isinstance(item, dict)]

    def discover(self) -> PodConnection | None:
        candidates: list[dict[str, Any]] = []
        for pod in self._list_pods():
            if pod.get("endpointId") is not None:
                continue
            if pod.get("templateId") != self.template_id:
                continue
            # The current v1 Pod response carries the location on the
            # attached networkVolume rather than on the Pod itself.
            volume = pod.get("networkVolume") or {}
            pod_data_center = pod.get("dataCenterId") or volume.get("dataCenterId")
            if pod_data_center != self.data_center_id:
                continue
            status = pod.get("desiredStatus") or pod.get("status")
            if status != "RUNNING":
                continue
            if self.name_prefix and not str(pod.get("name", "")).startswith(self.name_prefix):
                continue
            volume_id = pod.get("networkVolumeId") or volume.get("id")
            if volume_id != self.network_volume_id:
                continue
            # A Pod can declare an HTTP service without exposing a public HTTP
            # mapping. That is intentional here: the gateway reaches port
            # 8000 through the Pod's public SSH mapping and local forwarding.
            declared_ports = pod.get("ports") or []
            has_internal_port = any(
                str(item).split("/", 1)[0] == str(self.internal_port)
                for item in declared_ports
            )
            mappings = pod.get("portMappings") or {}
            if not has_internal_port and str(self.internal_port) not in mappings and self.internal_port not in mappings:
                continue
            candidates.append(pod)

        if not candidates:
            return None
        if len(candidates) > 1:
            ids = ", ".join(str(item.get("id")) for item in candidates)
            raise DiscoveryError(f"More than one matching running Pod found: {ids}")

        pod = candidates[0]
        volume = pod.get("networkVolume") or {}
        status = pod.get("desiredStatus") or pod.get("status")
        volume_id = pod.get("networkVolumeId") or volume.get("id")
        public_ip = pod.get("publicIp")
        mappings = pod.get("portMappings") or {}
        if not public_ip:
            return None
        public_port = mappings.get(str(self.internal_port), mappings.get(self.internal_port))
        if public_port is not None:
            try:
                public_port = int(public_port)
            except (TypeError, ValueError) as exc:
                raise DiscoveryError("Pod HTTP port mapping was not numeric") from exc
        ssh_public_port = mappings.get("22", mappings.get(22))
        if ssh_public_port is not None:
            try:
                ssh_public_port = int(ssh_public_port)
            except (TypeError, ValueError) as exc:
                raise DiscoveryError("Pod SSH port mapping was not numeric") from exc

        gpu = pod.get("gpu") or {}
        template_id = pod.get("templateId") or pod.get("template")
        # HTTP services are available through Runpod's stable per-Pod proxy
        # even when no public HTTP port mapping is returned by the v1 REST
        # response. This is also a useful fallback when direct SSH is not
        # available because the template did not inject a public key.
        base_url = f"https://{pod['id']}-{self.internal_port}.proxy.runpod.net"
        return PodConnection(
            pod_id=str(pod["id"]),
            name=str(pod.get("name", "")),
            desired_status=str(status),
            public_ip=str(public_ip),
            internal_port=self.internal_port,
            public_port=public_port,
            ssh_public_port=ssh_public_port,
            base_url=base_url,
            template_id=template_id,
            network_volume_id=volume_id,
            gpu_id=gpu.get("id"),
        )


def discovery_from_environment() -> RunpodPodDiscovery:
    api_key = os.getenv("RUNPOD_API_KEY") or os.getenv("RUNPOD_KEY", "")
    return RunpodPodDiscovery(
        api_key=api_key,
        api_base=os.getenv("RUNPOD_API_BASE", "https://rest.runpod.io/v1"),
        template_id=os.getenv("RUNPOD_POD_TEMPLATE_ID", "vof7vdwzcw"),
        data_center_id=os.getenv("RUNPOD_POD_DATA_CENTER", "EU-RO-1"),
        network_volume_id=os.getenv("RUNPOD_NETWORK_VOLUME_ID", "0dvyrxzx4s"),
        internal_port=int(os.getenv("POD_INTERNAL_PORT", "8000")),
        name_prefix=os.getenv("RUNPOD_POD_NAME_PREFIX", ""),
        timeout_seconds=float(os.getenv("RUNPOD_API_TIMEOUT_SECONDS", "5")),
    )
