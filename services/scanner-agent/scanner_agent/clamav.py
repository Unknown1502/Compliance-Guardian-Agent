"""Minimal clamd client — INSTREAM over a TCP socket.

Deliberately not the `clamd` PyPI package. The protocol needed here is one
command, the package is unmaintained, and a scanner is the last place to add a
dependency that nothing else in the image justifies. This is the same
reasoning that keeps the PayPal integration on urllib.

Every failure path returns a verdict rather than raising past the caller, and
none of those verdicts is CLEAN: a scanner that could not answer has not said
the file is safe.
"""

from __future__ import annotations

import logging
import re
import socket
import struct
from dataclasses import dataclass

from schema_validators import ScanStatus

logger = logging.getLogger("cg.scanner.clamav")

# clamd rejects a chunk larger than StreamMaxLength; 64 KiB is well under any
# default and keeps memory flat regardless of file size.
_CHUNK = 64 * 1024
_TERMINATOR = struct.pack("!L", 0)

_FOUND = re.compile(r"^stream:\s+(?P<threat>.+)\s+FOUND$")


@dataclass(frozen=True)
class ScanVerdict:
    status: ScanStatus
    threat_name: str = ""
    detail: str = ""

    @property
    def is_clean(self) -> bool:
        return self.status is ScanStatus.CLEAN


class ClamAVScanner:
    name = "clamav"

    def __init__(self, host: str, port: int = 3310, timeout: float = 120.0):
        self._host = host
        self._port = port
        self._timeout = timeout

    def version(self) -> str:
        """Signature database version — recorded on every scan record.

        Worth persisting: 'this file was scanned' means little without which
        signature set said so, and that is the first question asked when a
        threat is found later that an earlier scan missed.
        """
        try:
            with self._connect() as sock:
                sock.sendall(b"zVERSION\0")
                return self._read_response(sock)
        except OSError as exc:
            logger.warning("clamd VERSION failed: %s", exc)
            return ""

    def ping(self) -> bool:
        try:
            with self._connect() as sock:
                sock.sendall(b"zPING\0")
                return self._read_response(sock) == "PONG"
        except OSError:
            return False

    def scan(self, data: bytes) -> ScanVerdict:
        try:
            with self._connect() as sock:
                sock.sendall(b"zINSTREAM\0")
                for start in range(0, len(data), _CHUNK):
                    chunk = data[start : start + _CHUNK]
                    sock.sendall(struct.pack("!L", len(chunk)) + chunk)
                sock.sendall(_TERMINATOR)
                raw = self._read_response(sock)
        except socket.timeout:
            # Not INFECTED and emphatically not CLEAN. The file stays put.
            logger.warning("clamd timed out after %ss", self._timeout)
            return ScanVerdict(ScanStatus.SCAN_TIMEOUT, detail="scanner timed out")
        except OSError as exc:
            logger.warning("clamd unreachable: %s", exc)
            return ScanVerdict(ScanStatus.SCAN_FAILED, detail=f"scanner unreachable: {exc}")

        return self._interpret(raw)

    @staticmethod
    def _interpret(raw: str) -> ScanVerdict:
        if raw == "stream: OK":
            return ScanVerdict(ScanStatus.CLEAN)
        found = _FOUND.match(raw)
        if found:
            return ScanVerdict(ScanStatus.INFECTED, threat_name=found.group("threat"))
        # "INSTREAM size limit exceeded. ERROR", a truncated reply, anything
        # unrecognised. Unknown output is a failure, never a pass.
        logger.warning("unrecognised clamd reply: %r", raw)
        return ScanVerdict(ScanStatus.SCAN_FAILED, detail=raw[:200])

    def _connect(self) -> socket.socket:
        sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        sock.settimeout(self._timeout)
        return sock

    @staticmethod
    def _read_response(sock: socket.socket) -> str:
        buf = bytearray()
        while b"\0" not in buf:
            piece = sock.recv(4096)
            if not piece:
                break
            buf.extend(piece)
            if len(buf) > 8192:  # a reply is a few dozen bytes; this is junk
                break
        return buf.split(b"\0")[0].decode("utf-8", "replace").strip()
