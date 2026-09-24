"""Where the daemon's local API is and what its errors mean; shared by the CLI and the GUI."""

from dataclasses import dataclass
from typing import Any

from kse.config import Paths, SettingsError, load_settings, read_token
from kse.i18n import _

TIMEOUT = 15.0


class DaemonUnavailable(Exception):
    pass


class ApiError(Exception):
    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(format_detail(detail))
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @property
    def events_url(self) -> str:
        return self.base_url.replace("http://", "ws://", 1) + "/events"


def endpoint(paths: Paths | None = None) -> Endpoint:
    """The daemon's address and token, read from its files (they change when it restarts)."""
    paths = paths or Paths.default()
    token = read_token(paths.token)
    if token is None:
        raise DaemonUnavailable(_("no API token yet: the daemon has never run on this account"))
    try:
        port = load_settings(paths).port
    except SettingsError as exc:
        raise DaemonUnavailable(str(exc)) from None
    return Endpoint(base_url=f"http://127.0.0.1:{port}", token=token)


def unavailable(error: Exception) -> DaemonUnavailable:
    return DaemonUnavailable(_("the kse daemon is not running ({error})").format(error=error))


def error_from(status: int, body: Any, text: str) -> ApiError:
    detail = body.get("detail", text) if isinstance(body, dict) else text
    return ApiError(status, detail)


def format_detail(detail: Any) -> str:
    if isinstance(detail, list):  # pydantic validation errors
        lines = []
        for item in detail:
            where = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
            lines.append(f"{where}: {item.get('msg')}" if where else str(item.get("msg")))
        return "\n".join(lines)
    return str(detail)
