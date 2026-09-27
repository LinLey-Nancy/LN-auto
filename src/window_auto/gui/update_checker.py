"""Qt network layer for checking and downloading GitHub releases."""

from __future__ import annotations

import json

from PySide6.QtCore import QFile, QIODevice, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from window_auto.update import RELEASE_API_URL, ReleaseInfo, is_newer, parse_release
from window_auto.version import current_version


_REQUEST_TIMEOUT_MS = 15_000
_DOWNLOAD_TIMEOUT_MS = 60_000


def _build_request(url: str, timeout_ms: int) -> QNetworkRequest:
    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"User-Agent", f"LN-auto/{current_version()}".encode())
    request.setRawHeader(b"Accept", b"application/vnd.github+json")
    request.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
    )
    request.setTransferTimeout(timeout_ms)
    return request


class UpdateChecker(QObject):
    """Asynchronously compare the latest GitHub release with this version."""

    update_available = Signal(object)  # ReleaseInfo
    no_update = Signal()
    check_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

    def check(self) -> None:
        if self._reply is not None:
            return
        self._reply = self._network.get(
            _build_request(RELEASE_API_URL, _REQUEST_TIMEOUT_MS)
        )
        self._reply.finished.connect(self._on_finished)

    def _on_finished(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.check_failed.emit(reply.errorString())
                return
            raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
                release = parse_release(payload)
            except (ValueError, RuntimeError) as error:
                self.check_failed.emit(f"无法解析更新信息：{error}")
                return
            if is_newer(release.version, current_version()):
                self.update_available.emit(release)
            else:
                self.no_update.emit()
        finally:
            reply.deleteLater()


class UpdateDownloader(QObject):
    """Stream a release asset to disk with progress callbacks."""

    progressed = Signal(int, int)  # bytes received, total bytes (0 if unknown)
    succeeded = Signal(str)  # destination path
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._file: QFile | None = None
        self._destination = ""
        self._cancelled = False

    def start(self, url: str, destination: str) -> None:
        if self._reply is not None:
            return
        self._cancelled = False
        self._destination = destination
        self._file = QFile(destination)
        if not self._file.open(QIODevice.OpenModeFlag.WriteOnly):
            self.failed.emit(f"无法写入文件：{destination}")
            return
        self._reply = self._network.get(_build_request(url, _DOWNLOAD_TIMEOUT_MS))
        self._reply.readyRead.connect(self._on_ready_read)
        self._reply.downloadProgress.connect(self.progressed)
        self._reply.finished.connect(self._on_finished)

    def cancel(self) -> None:
        self._cancelled = True
        if self._reply is not None:
            self._reply.abort()

    def _on_ready_read(self) -> None:
        if self._reply is not None and self._file is not None:
            self._file.write(self._reply.readAll())

    def _on_finished(self) -> None:
        reply = self._reply
        self._reply = None
        if self._file is not None:
            self._file.close()
            self._file = None
        if reply is None:
            return
        try:
            if self._cancelled:
                QFile.remove(self._destination)
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                QFile.remove(self._destination)
                self.failed.emit(reply.errorString())
                return
            self.succeeded.emit(self._destination)
        finally:
            reply.deleteLater()
