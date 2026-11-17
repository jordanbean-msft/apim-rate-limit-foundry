import json

import pytest

from apim_rate_limit_foundry.streaming.usage import StreamUsage

CHAT_USAGE = b'data: {"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":3}}\n\n'


def responses_event(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


def assert_unknown(observer: StreamUsage) -> None:
    with pytest.raises(ValueError, match="terminal usage"):
        observer.finish()


def test_malformed_framing_latches_invalid_and_ignores_later_bytes() -> None:
    observer = StreamUsage("openai-chat")

    observer.feed(b"data: {not json}\n\n")
    observer.feed(CHAT_USAGE)

    assert observer.invalid and not observer.parser.buffer
    assert_unknown(observer)


def test_a_trailing_carriage_return_is_completed_when_the_stream_ends() -> None:
    observer = StreamUsage("openai-chat")

    observer.feed(CHAT_USAGE.rstrip(b"\n") + b"\r\r")

    assert observer.finish() == {"prompt_tokens": 8, "completion_tokens": 3}


def test_comment_only_events_carry_no_usage_and_are_ignored() -> None:
    observer = StreamUsage("openai-chat")

    observer.feed(b": keep-alive\n\n")
    observer.feed(CHAT_USAGE)

    assert observer.finish()["prompt_tokens"] == 8


@pytest.mark.parametrize(
    "events",
    [
        [CHAT_USAGE, CHAT_USAGE],
        [b'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":1}}\n\n'],
        [b'data: {"error":{"message":"boom"}}\n\n'],
        [b"data: [1, 2]\n\n"],
        [b"data: [DONE]\n\n"],
    ],
)
def test_ambiguous_or_failed_chat_streams_are_unknown(events: list[bytes]) -> None:
    observer = StreamUsage("openai-chat")

    for chunk in events:
        observer.feed(chunk)

    assert_unknown(observer)


def test_chat_accepts_one_done_marker_after_usage_but_not_two() -> None:
    observer = StreamUsage("openai-chat")
    observer.feed(CHAT_USAGE + b"data: [DONE]\n\n")
    assert observer.finish()["completion_tokens"] == 3

    observer.feed(b"data: [DONE]\n\n")
    assert_unknown(observer)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "response.failed", "response": {}},
        {"type": "error"},
        {"type": "response.completed", "response": {"status": "incomplete", "usage": {}}},
        {"type": "response.completed", "response": "done"},
        {"type": "response.completed", "response": {"status": "completed", "usage": "none"}},
    ],
)
def test_failed_or_inconsistent_responses_terminals_are_unknown(payload: dict) -> None:
    observer = StreamUsage("openai-responses")

    observer.feed(responses_event(payload))

    assert_unknown(observer)


THROTTLE = {"type": "error", "error": {"code": "rate_limit_exceeded", "message": "slow down"}}


def test_throttle_before_any_output_is_a_provider_rejection_with_no_usage() -> None:
    observer = StreamUsage("openai-responses")

    observer.feed(responses_event({"type": "response.created", "response": {"usage": None}}))
    observer.feed(responses_event(THROTTLE))

    assert observer.rejected
    assert_unknown(observer)


def test_response_failed_throttle_then_error_event_is_a_provider_rejection() -> None:
    observer = StreamUsage("openai-responses")
    failed = {
        "type": "response.failed",
        "response": {"status": "failed", "usage": None, "error": {"code": "rate_limit_exceeded"}},
    }

    observer.feed(responses_event({"type": "response.created", "response": {"usage": None}}))
    observer.feed(responses_event(failed))
    observer.feed(responses_event(THROTTLE))

    assert observer.rejected
    assert_unknown(observer)


@pytest.mark.parametrize(
    "events",
    [
        [{"type": "response.output_text.delta", "delta": "hi"}, THROTTLE],
        [{"type": "error", "error": {"code": "server_error"}}],
    ],
)
def test_errors_after_output_or_other_errors_are_not_free(events: list[dict]) -> None:
    observer = StreamUsage("openai-responses")

    for event in events:
        observer.feed(responses_event(event))

    assert not observer.rejected
    assert_unknown(observer)


def test_chat_content_marks_generation_so_a_later_throttle_is_still_charged() -> None:
    observer = StreamUsage("openai-chat")

    observer.feed(b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n')
    observer.feed(b'data: {"error":{"code":"rate_limit_exceeded"}}\n\n')

    assert not observer.rejected


def test_events_after_the_responses_terminal_are_ambiguous() -> None:
    observer = StreamUsage("openai-responses")
    terminal = {"type": "response.completed", "response": {"status": "completed", "usage": {}}}

    observer.feed(responses_event(terminal) + responses_event(terminal))

    assert_unknown(observer)


def test_oversized_data_cannot_share_an_event_with_other_data_lines() -> None:
    observer = StreamUsage("openai-responses", max_event_bytes=8192)
    oversized = b'data: {"type":"x","pad":"' + b"p" * 20_000 + b'"}\n'

    observer.feed(oversized + b'data: {"type":"response.output_text.delta"}\n\n')

    assert observer.invalid
    assert_unknown(observer)


def test_oversized_event_whose_json_never_completes_is_unknown() -> None:
    observer = StreamUsage("openai-responses", max_event_bytes=8192)

    observer.feed(b'data: {"type":"response.completed","pad":"' + b"p" * 20_000 + b"\n\n")

    assert observer.invalid
    assert_unknown(observer)


def test_a_second_oversized_data_line_in_one_event_is_unknown() -> None:
    observer = StreamUsage("openai-responses", max_event_bytes=8192)

    observer.feed(b"data: " + b"a" * 100 + b"\n" + b"data: " + b"b" * 9000 + b"\n\n")

    assert observer.invalid
