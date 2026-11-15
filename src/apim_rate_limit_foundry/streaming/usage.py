"""Incrementally inspect SSE framing and usage without storing generated content."""

import json
import re
from typing import Any

from apim_rate_limit_foundry.models.types import ApiProtocol


class StreamUsage:
    """Bounded SSE observation without retaining or modifying generated content."""

    def __init__(self, protocol: ApiProtocol, max_event_bytes: int = 65536) -> None:
        """Track at most one bounded event and one terminal provider usage object."""
        self.protocol = protocol
        self.max_event_bytes = max_event_bytes
        self.buffer = bytearray()
        self.lines: list[str] = []
        self.event_bytes = 0
        self.usage: dict[str, Any] | None = None
        self.complete = False
        self.terminated = False
        self.invalid = False

    def feed(self, chunk: bytes) -> None:
        """Observe arbitrary byte boundaries without disrupting stream forwarding.

        Invalid JSON, framing or oversized events latch invalid state and discard
        retained data. The relay can continue forwarding bytes, but finish() will
        reject the accounting observation instead of inventing token counters.
        """
        if self.invalid:
            return
        self.buffer.extend(chunk)
        try:
            while match := re.search(rb"\r\n|\r|\n", self.buffer):
                if match[0] == b"\r" and match.end() == len(self.buffer):
                    # Preserve a trailing CR until the next chunk can complete CRLF.
                    break
                line = bytes(self.buffer[: match.start()])
                del self.buffer[: match.end()]
                self.event_bytes += len(line) + len(match[0])
                if self.event_bytes > self.max_event_bytes:
                    raise ValueError("SSE event exceeds bound")
                if not line:
                    self._event()
                    self.lines.clear()
                    self.event_bytes = 0
                else:
                    self.lines.append(line.decode("utf-8"))
            if len(self.buffer) + self.event_bytes > self.max_event_bytes:
                raise ValueError("SSE event exceeds bound")
        except (ValueError, TypeError, KeyError):
            self.invalid = True
            self.buffer.clear()
            self.lines.clear()

    def finish(self) -> dict[str, Any]:
        """Return terminal provider usage or raise for incomplete/ambiguous state.

        A final CR can complete framing. Chat's optional [DONE] marker is recognized
        separately from its usage event; Responses supplies a completed/incomplete
        response event. Counters are normalized and priced later by the engine.
        """
        if self.buffer == b"\r":
            self.feed(b"\n")
        if self.invalid or self.buffer or self.lines or not self.complete or self.usage is None:
            raise ValueError("Stream lacks complete, unambiguous terminal usage")
        return self.usage

    def _event(self) -> None:
        """Consume one SSE event, ignoring non-data fields and nonterminal output."""
        data = "\n".join(
            line[5:].removeprefix(" ") for line in self.lines if line.startswith("data:")
        )
        if not data:
            return
        if data == "[DONE]":
            if self.protocol == "openai-chat" and self.usage is not None and not self.terminated:
                self.terminated = True
                return
            raise ValueError("Unexpected stream terminator")
        if self.complete:
            # Multiple terminal usage payloads cannot safely be priced as one request.
            raise ValueError("Data after terminal usage")
        payload = json.loads(data)
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
