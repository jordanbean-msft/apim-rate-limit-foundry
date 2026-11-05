import runpy
from unittest.mock import patch

import pytest


def test_module_entrypoint_honors_port_and_keeps_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setenv("LOCAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("LOCAL_STORE_ENABLED", "true")
    with patch("uvicorn.run") as server:
        runpy.run_module("apim_rate_limit_foundry.main", run_name="__main__")
    assert server.call_args.kwargs == {"host": "127.0.0.1", "port": 8123}
