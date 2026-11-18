"""Incremental Server-Sent Events framing with bounded retention."""

import re

LINE_TERMINATOR = re.compile(rb"\r\n|\r|\n")


class SseParser:
    """Turn arbitrary byte chunks into event payloads with bounded content retention.

    One event is held at a time. An event over ``max_event_bytes`` is a framing error,
    except for a single oversized ``data:`` line: when it matches ``terminal`` it is kept
    up to ``max_terminal_bytes`` so its usage can be read; otherwise it is discarded when
    ``discard_oversized`` is set. Anything else raises ``ValueError``.
    """

    def __init__(
        self,
        max_event_bytes: int,
        max_terminal_bytes: int,
        terminal: re.Pattern[bytes] | None = None,
        discard_oversized: bool = False,
    ) -> None:
        """Bind the retention bounds and the optional terminal-line pattern."""
        self.max_event_bytes = max_event_bytes
        self.max_terminal_bytes = max_terminal_bytes
        self.terminal = terminal
        self.discard_oversized = discard_oversized
        self.buffer = bytearray()
        self._data: list[str] = []
        self._event_bytes = 0
        self._discarded = False
        self._skipping = False
        self._scanned = 0

    def feed(self, chunk: bytes) -> list[str]:
        """Return the payloads of events completed by this chunk, joining their data lines."""
        self.buffer.extend(chunk)
        events: list[str] = []
        while True:
            match = LINE_TERMINATOR.search(self.buffer, self._scanned)
            if match is not None and match[0] == b"\r" and match.end() == len(self.buffer):
                # A final CR may be the first half of CRLF, so look at it again next time.
                self._scanned = match.start()
                match = None
            if match is None:
                self._scanned = max(self._scanned, len(self.buffer) - 1)
                self._partial_line()
                return events
            line = bytes(self.buffer[: match.start()])
            del self.buffer[: match.end()]
            self._scanned = 0
            self._line(line, len(match[0]), events)

    def close(self) -> list[str]:
        """Finish framing at end of stream, raising if an event is still incomplete."""
        events = self.feed(b"\n") if self.buffer.endswith(b"\r") else []
        if self.buffer or self._event_bytes or self._discarded or self._skipping:
            raise ValueError("Stream ended inside an event")
        return events

    def reset(self) -> None:
        """Discard everything retained, after a framing error."""
        self.buffer.clear()
        self._scanned = 0
        self._reset_event()
        self._skipping = False

    def _reset_event(self) -> None:
        self._data.clear()
        self._event_bytes = 0
        self._discarded = False

    def _line(self, line: bytes, terminator_length: int, events: list[str]) -> None:
        """Apply one terminated line: a blank line dispatches, data lines accumulate."""
        if self._skipping:
            self._skipping = False
            return
        if not line:
            if self._data:
                events.append("\n".join(self._data))
            self._reset_event()
            return
        size = self._event_bytes + len(line) + terminator_length
        if size > self.max_event_bytes and not self._admit_oversized(line, size):
            return
        self._event_bytes = size
        if line.startswith(b"data:"):
            if self._discarded:
                raise ValueError("Data after a discarded oversized line")
            self._data.append(line[len(b"data:") :].decode("utf-8").removeprefix(" "))

    def _partial_line(self) -> None:
        """Keep an unterminated remainder bounded, holding a trailing CR for a possible CRLF."""
        held = 1 if self.buffer.endswith(b"\r") else 0
        pending = len(self.buffer) - held
        if self._skipping:
            del self.buffer[:pending]
            self._scanned = 0
        elif pending and self._event_bytes + pending > self.max_event_bytes:
            # Only the line's start is needed to classify it, so avoid copying a growing buffer.
            if self._admit_oversized(bytes(self.buffer[:128]), self._event_bytes + pending):
                return
            self._skipping = True
            del self.buffer[:pending]
            self._scanned = 0

    def _admit_oversized(self, line: bytes, size: int) -> bool:
        """Keep a terminal line within its larger bound; otherwise discard it or raise."""
        if self._data or self._discarded or not line.startswith(b"data:"):
            raise ValueError("SSE event exceeds bound")
        if self.terminal is not None and self.terminal.match(line) is not None:
            if size > self.max_terminal_bytes:
                raise ValueError("Terminal SSE event exceeds bound")
            return True
        if not self.discard_oversized:
            raise ValueError("SSE event exceeds bound")
        self._discarded = True
        return False
