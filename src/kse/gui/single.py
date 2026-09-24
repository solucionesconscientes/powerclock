"""One kse-gui per user: a second start passes its request ("show") to the running one
through a local socket and exits."""

from collections.abc import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket

WAIT_MS = 300


class SingleInstance:
    def __init__(self, name: str) -> None:
        self.name = name
        self._server: QLocalServer | None = None

    def forward(self, request: str) -> bool:
        """Give `request` to the instance already running; False if there is none."""
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(WAIT_MS):
            return False
        socket.write(request.encode())
        socket.waitForBytesWritten(WAIT_MS)
        socket.disconnectFromServer()
        return True

    def listen(self, on_request: Callable[[str], None]) -> None:
        QLocalServer.removeServer(self.name)  # left behind if a previous instance crashed
        server = QLocalServer()
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.listen(self.name)
        server.newConnection.connect(lambda: self._accept(server, on_request))
        self._server = server

    @staticmethod
    def _accept(server: QLocalServer, on_request: Callable[[str], None]) -> None:
        socket = server.nextPendingConnection()
        if socket is None:
            return

        def read() -> None:
            on_request(bytes(socket.readAll().data()).decode(errors="replace").strip())
            socket.disconnectFromServer()

        socket.readyRead.connect(read)
        socket.disconnected.connect(socket.deleteLater)
