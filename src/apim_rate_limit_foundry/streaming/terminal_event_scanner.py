"""Extract only the terminal fields of one oversized JSON event without retaining it."""

import json
import re
from typing import Any

QUOTE_OR_BACKSLASH = re.compile(rb'["\\]')
MAX_STRING_BYTES = 256
WHITESPACE = b" \t\r\n"


class TerminalEventScanner:
    """Incrementally read ``type``, ``error``, ``response.status`` and ``response.usage``.

    Responses ``response.completed`` embeds the whole generated output, so it can
    exceed any sensible event bound. This scanner tracks JSON structure byte by
    byte and keeps only short shallow strings and the raw ``usage`` object, which
    is capped at ``max_usage_bytes``. Everything else, including ``output``, is
    discarded as it streams past.
    """

    def __init__(self, max_usage_bytes: int) -> None:
        """Start before the opening brace of one JSON object."""
        self.max_usage_bytes = max_usage_bytes
        self.stack: list[bool] = []
        self.expect_key: list[bool] = []
        self.keys: dict[int, str] = {}
        self.complete = False
        self.in_string = False
        self.escaped = False
        self.is_key = False
        self.string = bytearray()
        self.capturing = False
        self.usage = bytearray()
        self.usage_text: bytes | None = None
        self.type: str | None = None
        self.status: str | None = None
        self.has_error = False

    def feed(self, data: bytes) -> None:
        """Consume the next bytes of the object, which may split any token."""
        index = 0
        while index < len(data):
            if self.in_string:
                index = self._string(data, index)
            else:
                self._structural(data[index])
                index += 1

    def result(self) -> dict[str, Any]:
        """Return a minimal event payload, raising ``ValueError`` if the JSON is incomplete."""
        if not self.complete:
            raise ValueError("Incomplete oversized event")
        payload: dict[str, Any] = {"type": self.type}
        if self.has_error:
            payload["error"] = True
        response: dict[str, Any] = {}
        if self.status is not None:
            response["status"] = self.status
        if self.usage_text is not None:
            response["usage"] = json.loads(self.usage_text)
        if response:
            payload["response"] = response
        return payload

    def _structural(self, byte: int) -> None:
        """Handle one byte outside a string."""
        char = chr(byte)
        if not self.stack and byte not in WHITESPACE and (char != "{" or self.complete):
            raise ValueError("Oversized event is not a single JSON object")
        if self.capturing:
            self._capture(bytes([byte]))
        if char == '"':
            self.in_string = True
            self.string.clear()
            self.is_key = self.expect_key[-1]
        elif char in "{[":
            self._open(char == "{")
        elif char in "}]":
            self._close()
        elif char == ",":
            self.expect_key[-1] = self.stack[-1]
        elif char == ":":
            self.expect_key[-1] = False

    def _open(self, is_object: bool) -> None:
        if (
            len(self.stack) == 2
            and self.keys.get(1) == "response"
            and self.keys.get(2) == "usage"
            and is_object
        ):
            self.capturing = True
            self.usage = bytearray(b"{")
        self.stack.append(is_object)
        self.expect_key.append(is_object)

    def _close(self) -> None:
        self.stack.pop()
        self.expect_key.pop()
        if self.capturing and len(self.stack) == 2:
            self.capturing = False
            self.usage_text = bytes(self.usage)
        self.complete = not self.stack

    def _string(self, data: bytes, index: int) -> int:
        """Consume string content up to the next quote or backslash, returning the new index."""
        if self.escaped:
            self._collect(data[index : index + 1])
            self.escaped = False
            return index + 1
        match = QUOTE_OR_BACKSLASH.search(data, index)
        end = match.start() if match else len(data)
        self._collect(data[index:end])
        if match is None:
            return end
        if match[0] == b'"':
            self._end_string()
        else:
            self._collect(b"\\")
            self.escaped = True
        return end + 1

    def _collect(self, chunk: bytes) -> None:
        """Retain short shallow strings and, while capturing, the usage object's bytes."""
        if self.capturing:
            self._capture(chunk)
        if len(self.stack) <= 2 and len(self.string) <= MAX_STRING_BYTES:
            self.string.extend(chunk)

    def _capture(self, chunk: bytes) -> None:
        self.usage.extend(chunk)
        if len(self.usage) > self.max_usage_bytes:
            raise ValueError("Usage object exceeds bound")

    def _end_string(self) -> None:
        self.in_string = False
        if self.capturing:
            self._capture(b'"')
        depth = len(self.stack)
        if depth > 2:
            return
        text = (
            ""
            if len(self.string) > MAX_STRING_BYTES
            else json.loads(b'"' + bytes(self.string) + b'"')
        )
        if self.is_key:
            self.keys[depth] = text
            self.has_error = self.has_error or (depth == 1 and text == "error")
        elif depth == 1 and self.keys.get(1) == "type":
            self.type = text
        elif depth == 2 and self.keys.get(1) == "response" and self.keys.get(2) == "status":
            self.status = text
