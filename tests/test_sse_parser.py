import pytest

from apim_rate_limit_foundry.streaming.sse_parser import SseParser
from apim_rate_limit_foundry.streaming.usage import RESPONSES_TERMINAL, StreamUsage


def parser(**changes: object) -> SseParser:
    options: dict = {"max_event_bytes": 64, "max_terminal_bytes": 512, **changes}
    return SseParser(**options)


@pytest.mark.parametrize("chunk_size", [1, 3, 100])
def test_events_are_framed_across_any_chunk_and_line_ending_boundary(chunk_size: int) -> None:
    stream = b": ping\r\ndata: one\r\ndata: two\r\n\r\nevent: x\rdata: three\r\r"
    sse = parser()
    events: list[str] = []

    for start in range(0, len(stream), chunk_size):
        events += sse.feed(stream[start : start + chunk_size])
    events += sse.close()

    assert events == ["one\ntwo", "three"]


def test_an_event_cut_off_before_its_blank_line_is_an_error() -> None:
    sse = parser()
    sse.feed(b"data: partial\n")

    with pytest.raises(ValueError, match="inside an event"):
        sse.close()


def test_oversized_lines_are_rejected_unless_discarding_is_enabled() -> None:
    line = b"data: " + b"x" * 200 + b"\n\n"

    with pytest.raises(ValueError, match="exceeds"):
        parser().feed(line)
    sse = parser(discard_oversized=True)
    assert sse.feed(line + b"data: next\n\n") == ["next"]


def test_only_the_terminal_pattern_is_retained_up_to_its_larger_bound() -> None:
    sse = parser(terminal=RESPONSES_TERMINAL)
    terminal = b'data: {"type":"response.completed","pad":"' + b"p" * 300 + b'"}\n\n'

    assert len(sse.feed(terminal)) == 1
    with pytest.raises(ValueError, match="Terminal"):
        sse.feed(terminal.replace(b"p" * 300, b"p" * 600))


def test_an_oversized_line_cannot_follow_other_data_in_its_event() -> None:
    sse = parser(discard_oversized=True)
    sse.feed(b"data: small\n")

    with pytest.raises(ValueError, match="exceeds"):
        sse.feed(b"data: " + b"x" * 200 + b"\n")


def test_terminal_usage_larger_than_the_usage_bound_is_unknown() -> None:
    usage = '{"input_tokens":1,"pad":"' + "u" * 9000 + '"}'
    observer = StreamUsage("openai-responses")
    observer.feed(
        ('{"type":"response.completed","response":{"status":"completed","usage":' + usage + "}}")
        .join(["data: ", "\n\n"])
        .encode()
    )

    with pytest.raises(ValueError, match="terminal usage"):
        observer.finish()
