import json
import re
from typing import Any

from apim_rate_limit_foundry.models.types import ApiProtocol


class StreamUsage:
    """Bounded SSE observation without retaining or modifying generated content."""

    def __init__(self, protocol: ApiProtocol, max_event_bytes: int = 65536) -> None:
        self.protocol = protocol
        self.max_event_bytes = max_event_bytes
        self.buffer = bytearray()
        self.lines: list[str] = []
        self.event_bytes = 0
        self.usage: dict[str, Any] | None = None
        self.complete = False
        self.invalid = False
        self.started = False
        self.delta_seen = False

    def feed(self, chunk: bytes) -> None:
        if self.invalid:
            return
        self.buffer.extend(chunk)
        try:
            while match := re.search(rb"\r\n|\r|\n", self.buffer):
                if match[0] == b"\r" and match.end() == len(self.buffer):
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
        if self.buffer == b"\r":
            self.feed(b"\n")
        if self.invalid or self.buffer or self.lines or not self.complete or self.usage is None:
            raise ValueError("Stream lacks complete, unambiguous terminal usage")
        return self.usage

    def _event(self) -> None:
        data = "\n".join(
            line[5:].removeprefix(" ") for line in self.lines if line.startswith("data:")
        )
        if not data:
            return
        if data == "[DONE]":
            if self.protocol == "openai-chat" and self.usage is not None and not self.complete:
                self.complete = True
                return
            raise ValueError("Unexpected stream terminator")
        if self.complete:
            raise ValueError("Data after terminal usage")
        payload = json.loads(data)
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("Invalid provider event")
        if self.protocol == "openai-chat":
            if payload.get("usage") is not None:
                if self.usage is not None or payload.get("choices") != []:
                    raise ValueError("Ambiguous Chat usage")
                self.usage = self._usage(payload["usage"])
        elif self.protocol == "openai-responses":
            kind = payload.get("type")
            if kind in ("response.completed", "response.incomplete"):
                response = payload["response"]
                expected = "completed" if kind == "response.completed" else "incomplete"
                if not isinstance(response, dict) or response.get("status") != expected:
                    raise ValueError("Invalid terminal response")
                self.usage = self._usage(response["usage"])
                self.complete = True
            elif kind in ("error", "response.failed"):
                raise ValueError("Provider stream failed")
        else:
            self._anthropic(payload)

    def _anthropic(self, payload: dict[str, Any]) -> None:
        kind = payload.get("type")
        if kind == "message_start":
            if self.started:
                raise ValueError("Duplicate message start")
            self.usage = self._usage(payload["message"]["usage"])
            self.started = True
        elif kind == "message_delta":
            if not self.started or self.usage is None:
                raise ValueError("Message delta before start")
            update = self._usage(payload["usage"])
            old, new = self.usage.get("output_tokens"), update.get("output_tokens")
            if type(old) is not int or type(new) is not int or new < old:
                raise ValueError("Output usage must be cumulative")
            self.usage = {**self.usage, **update}
            self.delta_seen = True
        elif kind == "message_stop":
            if not self.started or not self.delta_seen:
                raise ValueError("Message stopped without final usage")
            self.complete = True
        elif kind == "error":
            raise ValueError("Provider stream failed")

    @staticmethod
    def _usage(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Usage object is required")
        return value
