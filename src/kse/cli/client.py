"""HTTP client of the daemon's local API, for the CLI."""

from typing import Any

import httpx

from kse.config import Paths, SettingsError, load_settings, read_token
from kse.i18n import _

TIMEOUT = 15.0


class DaemonUnavailable(Exception):
    pass


class ApiError(Exception):
    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(_format_detail(detail))
        self.status = status
        self.detail = detail


class Client:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise DaemonUnavailable(
                _("the kse daemon is not running ({error})").format(error=exc)
            ) from None
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(response.status_code, detail)
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
    paths = paths or Paths.default()
    token = read_token(paths.token)
    if token is None:
        raise DaemonUnavailable(_("no API token yet: the daemon has never run on this account"))
    try:
        port = load_settings(paths).port
    except SettingsError as exc:
        raise DaemonUnavailable(str(exc)) from None
    http = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    return Client(http)


def _format_detail(detail: Any) -> str:
    if isinstance(detail, list):  # pydantic validation errors
        lines = []
        for item in detail:
            where = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
            lines.append(f"{where}: {item.get('msg')}" if where else str(item.get("msg")))
        return "\n".join(lines)
    return str(detail)
