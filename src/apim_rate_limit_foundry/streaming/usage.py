"""Read terminal provider usage from an SSE stream without storing generated content."""

import json
import re
from typing import Any

from apim_rate_limit_foundry.models.types import ApiProtocol
from apim_rate_limit_foundry.streaming.sse_parser import SseParser

# A Responses stream ends with one event embedding the whole output, so it may exceed the
# ordinary event bound. Only that event is retained in full, up to this hard cap.
RESPONSES_TERMINAL = re.compile(rb'data: ?\{\s*"type"\s*:\s*"response\.(?:completed|incomplete)"')
MAX_TERMINAL_EVENT_BYTES = 1_048_576
MAX_USAGE_BYTES = 8192


class StreamUsage:
    """Bounded SSE observation that yields the one terminal usage object or fails closed.

    Invalid JSON, framing or an ambiguous terminal latches ``invalid``: the relay keeps
    forwarding bytes, but ``finish()`` then rejects the observation instead of inventing
    token counters. Counters are normalized and priced later by the engine.
    """

    def __init__(self, protocol: ApiProtocol, max_event_bytes: int = 65536) -> None:
        """Retain at most one bounded event; oversized Responses output events are skipped."""
        responses = protocol == "openai-responses"
        self.protocol = protocol
        self.parser = SseParser(
            max_event_bytes,
            MAX_TERMINAL_EVENT_BYTES,
            terminal=RESPONSES_TERMINAL if responses else None,
            discard_oversized=responses,
        )
        self.usage: dict[str, Any] | None = None
        self.complete = False
        self.terminated = False
        self.invalid = False
        self.generating = False
        self.rejected = False

    def feed(self, chunk: bytes) -> None:
        """Observe arbitrary byte boundaries without disrupting stream forwarding."""
        if self.invalid:
            return
        try:
            for data in self.parser.feed(chunk):
                self._event(data)
        except (ValueError, TypeError, KeyError):
            self._invalidate()

    def finish(self) -> dict[str, Any]:
        """Return terminal provider usage or raise for incomplete/ambiguous state.

        A final CR can complete framing. Chat's optional [DONE] marker is recognized
        separately from its usage event; Responses supplies a completed/incomplete
        response event.
        """
        if not self.invalid:
            try:
                for data in self.parser.close():
                    self._event(data)
            except (ValueError, TypeError, KeyError):
                self._invalidate()
        if self.invalid or not self.complete or self.usage is None:
            raise ValueError("Stream lacks complete, unambiguous terminal usage")
        return self.usage

    def _invalidate(self) -> None:
        self.invalid = True
        self.parser.reset()

    def _event(self, data: str) -> None:
        """Consume one SSE event payload, ignoring empty events."""
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
        self._note_generation(payload)
        if self._is_throttle_rejection(payload):
            self.rejected = True
            raise ValueError("Provider throttled the request before generating output")
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

    def _note_generation(self, payload: Any) -> None:
        """Remember once the provider has produced any output, which may be billed."""
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if isinstance(kind, str) and ("delta" in kind or "output_item" in kind):
            self.generating = True
        if payload.get("choices"):
            self.generating = True

    def _is_throttle_rejection(self, payload: Any) -> bool:
        """A throttle error before any output means the request consumed no tokens.

        Azure reports it as a top-level ``error`` event or as ``response.failed``
        carrying ``response.error``, usually both in sequence.
        """
        if not isinstance(payload, dict) or self.generating:
            return False
        error = payload.get("error")
        response = payload.get("response")
        if not isinstance(error, dict) and isinstance(response, dict):
            error = response.get("error")
        return isinstance(error, dict) and error.get("code") == "rate_limit_exceeded"

    @staticmethod
    def _usage(value: Any) -> dict[str, Any]:
        """Require a bounded provider usage object without making counters up."""
        if not isinstance(value, dict) or len(json.dumps(value)) > MAX_USAGE_BYTES:
            raise ValueError("A bounded usage object is required")
        return value
