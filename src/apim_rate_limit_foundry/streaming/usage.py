"""Incrementally inspect SSE framing and usage without storing generated content."""

import json
import re
from typing import Any

from apim_rate_limit_foundry.models.types import ApiProtocol
from apim_rate_limit_foundry.streaming.terminal_event_scanner import TerminalEventScanner

LINE_TERMINATOR = re.compile(rb"\r\n|\r|\n")


class StreamUsage:
    """Bounded SSE observation without retaining or modifying generated content."""

    def __init__(self, protocol: ApiProtocol, max_event_bytes: int = 65536) -> None:
        """Track at most one bounded event and one terminal provider usage object.

        The bound applies to retained bytes. A Responses ``data:`` line beyond it
        (``response.completed`` embeds the full output) is scanned as it streams
        and only its type, status and usage are kept.
        """
        self.protocol = protocol
        self.max_event_bytes = max_event_bytes
        self.buffer = bytearray()
        self.lines: list[str] = []
        self.event_bytes = 0
        self.scanner: TerminalEventScanner | None = None
        self.oversized: dict[str, Any] | None = None
        self.usage: dict[str, Any] | None = None
        self.complete = False
        self.terminated = False
        self.invalid = False

    def feed(self, chunk: bytes) -> None:
        """Observe arbitrary byte boundaries without disrupting stream forwarding.

        Invalid JSON, framing or oversized non-Responses events latch invalid state
        and discard retained data. The relay can continue forwarding bytes, but
        finish() will reject the accounting observation instead of inventing token
        counters.
        """
        if self.invalid:
            return
        self.buffer.extend(chunk)
        try:
            self._drain()
        except (ValueError, TypeError, KeyError):
            self.invalid = True
            self.buffer.clear()
            self.lines.clear()
            self.scanner = None
            self.oversized = None

    def finish(self) -> dict[str, Any]:
        """Return terminal provider usage or raise for incomplete/ambiguous state.

        A final CR can complete framing. Chat's optional [DONE] marker is recognized
        separately from its usage event; Responses supplies a completed/incomplete
        response event. Counters are normalized and priced later by the engine.
        """
        if self.buffer == b"\r":
            self.feed(b"\n")
        if (
            self.invalid
            or self.buffer
            or self.lines
            or self.scanner is not None
            or self.oversized is not None
            or not self.complete
            or self.usage is None
        ):
            raise ValueError("Stream lacks complete, unambiguous terminal usage")
        return self.usage

    def _drain(self) -> None:
        """Process complete lines, then bound or scan the unterminated remainder."""
        while match := LINE_TERMINATOR.search(self.buffer):
            if match[0] == b"\r" and match.end() == len(self.buffer):
                # Preserve a trailing CR until the next chunk can complete CRLF.
                break
            line = bytes(self.buffer[: match.start()])
            del self.buffer[: match.end()]
            self._line(line, len(match[0]))
        self._partial_line()

    def _line(self, line: bytes, terminator_length: int) -> None:
        """Apply one terminated line, ending an in-progress oversized line when present."""
        if self.scanner is not None:
            self.scanner.feed(line)
            self._end_scan()
        elif not line:
            self._event()
            self.lines.clear()
            self.event_bytes = 0
        elif self.event_bytes + len(line) + terminator_length > self.max_event_bytes:
            self._start_scan(line)
            self._end_scan()
        else:
            self.event_bytes += len(line) + terminator_length
            self.lines.append(line.decode("utf-8"))

    def _partial_line(self) -> None:
        """Keep an unterminated remainder bounded, scanning it once it exceeds the bound."""
        held = 1 if self.buffer.endswith(b"\r") else 0
        pending = bytes(self.buffer[: len(self.buffer) - held])
        if self.scanner is None and len(self.buffer) + self.event_bytes > self.max_event_bytes:
            self._start_scan(pending)
        elif self.scanner is not None:
            self.scanner.feed(pending)
        else:
            return
        del self.buffer[: len(pending)]

    def _start_scan(self, line: bytes) -> None:
        """Begin scanning a Responses data line too large to retain."""
        if (
            self.protocol != "openai-responses"
            or not line.startswith(b"data:")
            or any(retained.startswith("data:") for retained in self.lines)
        ):
            raise ValueError("SSE event exceeds bound")
        self.scanner = TerminalEventScanner(self.max_event_bytes)
        self.scanner.feed(line[len(b"data:") :])

    def _end_scan(self) -> None:
        """Keep the scanner's minimal payload for the event ending at the next blank line."""
        assert self.scanner is not None
        self.oversized = self.scanner.result()
        self.scanner = None

    def _event(self) -> None:
        """Consume one SSE event, ignoring non-data fields and nonterminal output."""
        data_lines = [line[5:].removeprefix(" ") for line in self.lines if line.startswith("data:")]
        oversized, self.oversized = self.oversized, None
        if oversized is not None:
            if data_lines:
                raise ValueError("Oversized event combined with other data")
            self._apply(oversized)
            return
        data = "\n".join(data_lines)
        if not data:
            return
        if data == "[DONE]":
            if self.protocol == "openai-chat" and self.usage is not None and not self.terminated:
                self.terminated = True
                return
            raise ValueError("Unexpected stream terminator")
        self._apply(json.loads(data))

    def _apply(self, payload: Any) -> None:
        """Record terminal usage from one decoded provider event."""
        if self.complete:
            # Multiple terminal usage payloads cannot safely be priced as one request.
            raise ValueError("Data after terminal usage")
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("Invalid provider event")
        if self.protocol == "openai-chat":
            if payload.get("usage") is not None:
                if self.usage is not None or payload.get("choices") != []:
                    raise ValueError("Ambiguous Chat usage")
                self.usage = self._usage(payload["usage"])
                self.complete = True
        elif self.protocol == "openai-responses":
            kind = payload.get("type")
            if kind in ("response.completed", "response.incomplete"):
                response = payload["response"]
                expected_status = kind.removeprefix("response.")
                if not isinstance(response, dict) or response.get("status") != expected_status:
                    raise ValueError("Invalid terminal response")
                self.usage = self._usage(response["usage"])
                self.complete = True
            elif kind in ("error", "response.failed"):
                raise ValueError("Provider stream failed")

    @staticmethod
    def _usage(value: Any) -> dict[str, Any]:
        """Require a provider usage object without making protocol-specific counters up."""
        if not isinstance(value, dict):
            raise ValueError("Usage object is required")
        return value
