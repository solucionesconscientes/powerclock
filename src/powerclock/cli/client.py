"""HTTP client of the daemon's local API, for the CLI."""

from typing import Any

import httpx

from powerclock.config import Paths
from powerclock.connection import (
    TIMEOUT,
    ApiError,
    DaemonUnavailable,
    endpoint,
    error_from,
    unavailable,
)

__all__ = ["ApiError", "Client", "DaemonUnavailable", "connect"]


class Client:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise unavailable(exc) from None
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = None
            raise error_from(response.status_code, body, response.text)
        return response.json() if response.content else None

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)


def connect(paths: Paths | None = None) -> Client:
    where = endpoint(paths)
    http = httpx.Client(base_url=where.base_url, headers=where.headers, timeout=TIMEOUT)
    return Client(http)
