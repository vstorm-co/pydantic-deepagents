"""Discovering what local inference servers serve (#216)."""

from __future__ import annotations

import httpx
import pytest

from apps.cli.local_models import (
    DEFAULT_OLLAMA_HOST,
    ollama_host,
    ollama_models,
    openai_compatible_models,
)


def _serving(
    routes: dict[str, httpx.Response], seen: list[httpx.Request] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestOpenAICompatible:
    def test_the_models_listing_becomes_model_strings(self) -> None:
        client = _serving(
            {
                "http://localhost:8080/v1/models": httpx.Response(
                    200, json={"data": [{"id": "qwen2.5"}, {"id": "phi-4"}]}
                )
            }
        )

        assert openai_compatible_models("http://localhost:8080/v1/", client=client) == [
            "openai-compatible:qwen2.5",
            "openai-compatible:phi-4",
        ]

    def test_the_keystore_key_is_sent_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A keyed vLLM refuses the listing as it refuses the model calls."""
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "sk-local")
        seen: list[httpx.Request] = []
        client = _serving({"http://h/v1/models": httpx.Response(200, json={"data": []})}, seen)

        openai_compatible_models("http://h/v1", client=client)

        assert seen[0].headers["Authorization"] == "Bearer sk-local"

    def test_no_base_url_asks_nothing(self) -> None:
        assert openai_compatible_models(None) == []

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(500),
            httpx.Response(200, json={"models": []}),
            httpx.Response(200, text="<html>"),
        ],
        ids=["server-error", "another-shape", "not-json"],
    )
    def test_anything_unexpected_is_nothing_discovered(self, response: httpx.Response) -> None:
        client = _serving({"http://h/v1/models": response})

        assert openai_compatible_models("http://h/v1", client=client) == []

    def test_a_server_that_is_down_is_nothing_discovered(self) -> None:
        assert openai_compatible_models("http://127.0.0.1:9/v1") == []


class TestOllama:
    def test_pulled_models_become_model_strings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        client = _serving(
            {
                f"{DEFAULT_OLLAMA_HOST}/api/tags": httpx.Response(
                    200, json={"models": [{"name": "llama3.3"}]}
                )
            }
        )

        assert ollama_models(client=client) == ["ollama:llama3.3"]

    def test_anything_unexpected_is_nothing_discovered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        client = _serving(
            {f"{DEFAULT_OLLAMA_HOST}/api/tags": httpx.Response(200, json={"data": []})}
        )

        assert ollama_models(client=client) == []

    @pytest.mark.parametrize(
        ("configured", "host"),
        [
            (None, DEFAULT_OLLAMA_HOST),
            ("http://gpu-box:11434/v1", "http://gpu-box:11434"),
            ("http://gpu-box:11434/", "http://gpu-box:11434"),
        ],
    )
    def test_the_host_follows_ollama_base_url(
        self, monkeypatch: pytest.MonkeyPatch, configured: str | None, host: str
    ) -> None:
        """The same variable the model calls read, without the `/v1` they add."""
        if configured is None:
            monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        else:
            monkeypatch.setenv("OLLAMA_BASE_URL", configured)

        assert ollama_host() == host
