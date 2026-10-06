"""Messages from outside the terminal into a live TUI session (#181)."""

from __future__ import annotations

import asyncio
import json
import socket
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from apps.cli.external_messages import (
    ENDPOINT_FILE,
    Delivery,
    ExternalMessage,
    ExternalMessageRefused,
    SessionEndpoint,
)
from tests.test_tui import _queue_app, _settle


class _Recorder:
    """An `Inject` that records what reached it and answers as told."""

    def __init__(self) -> None:
        self.messages: list[ExternalMessage] = []
        self.answer: Delivery | Exception = "queued"

    def __call__(self, message: ExternalMessage) -> Delivery:
        self.messages.append(message)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def inject() -> _Recorder:
    return _Recorder()


@pytest.fixture
def endpoint(inject: _Recorder, tmp_path: Path) -> Iterator[SessionEndpoint]:
    served = SessionEndpoint(inject, tmp_path)
    served.start()
    yield served
    served.stop()


def _published(state_dir: Path) -> dict[str, Any]:
    published: dict[str, Any] = json.loads((state_dir / ENDPOINT_FILE).read_text())
    return published


def _post(state_dir: Path, body: Any, *, token: str | None = None, **kwargs: Any) -> httpx.Response:
    published = _published(state_dir)
    token = published["token"] if token is None else token
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.post(published["url"], json=body, headers=headers, **kwargs)


class TestEndpoint:
    def test_a_message_reaches_the_session(
        self, endpoint: SessionEndpoint, inject: _Recorder, tmp_path: Path
    ) -> None:
        response = _post(
            tmp_path,
            {
                "text": "also check MR 123",
                "source": "slack",
                "mode": "steer",
                "metadata": {"thread": "C1:17"},
            },
        )

        assert response.status_code == 202
        assert response.json() == {"delivery": "queued"}
        assert inject.messages == [
            ExternalMessage(
                text="also check MR 123", source="slack", mode="steer", metadata={"thread": "C1:17"}
            )
        ]

    def test_it_listens_on_loopback_only(self, endpoint: SessionEndpoint) -> None:
        assert endpoint.url.startswith("http://127.0.0.1:")

    def test_the_token_file_is_readable_by_the_owner_only(
        self, endpoint: SessionEndpoint, tmp_path: Path
    ) -> None:
        mode = stat.S_IMODE((tmp_path / ENDPOINT_FILE).stat().st_mode)

        assert mode == 0o600
        assert _published(tmp_path)["url"] == endpoint.url

    @pytest.mark.parametrize("token", ["", "not-the-token"], ids=["none", "wrong"])
    def test_without_the_token_nothing_is_delivered(
        self, endpoint: SessionEndpoint, inject: _Recorder, tmp_path: Path, token: str
    ) -> None:
        response = _post(tmp_path, {"text": "hi", "source": "slack"}, token=token)

        assert response.status_code == 401
        assert inject.messages == []

    @pytest.mark.parametrize(
        "body",
        [
            {"source": "slack"},
            {"text": "", "source": "slack"},
            {"text": "hi", "source": "slack bot"},
            {"text": "hi", "source": "slack", "mode": "interrupt"},
            "not an object",
        ],
        ids=["no-text", "empty-text", "source-with-space", "unknown-mode", "not-an-object"],
    )
    def test_a_malformed_body_is_refused(
        self, endpoint: SessionEndpoint, inject: _Recorder, tmp_path: Path, body: Any
    ) -> None:
        response = _post(tmp_path, body)

        assert response.status_code == 400
        assert inject.messages == []

    def test_a_refusal_reaches_the_sender(
        self, endpoint: SessionEndpoint, inject: _Recorder, tmp_path: Path
    ) -> None:
        inject.answer = ExternalMessageRefused("a fork is active")

        response = _post(tmp_path, {"text": "hi", "source": "ci"})

        assert response.status_code == 409
        assert response.json() == {"error": "a fork is active"}

    def test_a_failure_is_a_500_not_a_dropped_connection(
        self, endpoint: SessionEndpoint, inject: _Recorder, tmp_path: Path
    ) -> None:
        inject.answer = RuntimeError("boom")

        response = _post(tmp_path, {"text": "hi", "source": "ci"})

        assert response.status_code == 500
        assert "boom" not in response.text

    def test_an_oversized_body_is_not_read(
        self, endpoint: SessionEndpoint, inject: _Recorder, tmp_path: Path
    ) -> None:
        response = _post(tmp_path, {"text": "x" * 70_000, "source": "ci"})

        assert response.status_code == 413
        assert inject.messages == []

    def test_an_invalid_content_length_is_refused(
        self, endpoint: SessionEndpoint, tmp_path: Path
    ) -> None:
        published = _published(tmp_path)
        port = int(published["url"].split(":")[2].split("/")[0])
        request = (
            "POST /messages HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"Authorization: Bearer {published['token']}\r\nContent-Length: many\r\n\r\n"
        )
        with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
            conn.sendall(request.encode())
            status_line = conn.makefile("rb").readline()

        assert b" 400 " in status_line

    def test_other_paths_are_not_found(self, endpoint: SessionEndpoint, tmp_path: Path) -> None:
        published = _published(tmp_path)
        url = published["url"].removesuffix("/messages") + "/other"

        response = httpx.post(url, headers={"Authorization": f"Bearer {published['token']}"})

        assert response.status_code == 404


class TestEndpointFile:
    def test_stopping_withdraws_the_file(self, inject: _Recorder, tmp_path: Path) -> None:
        served = SessionEndpoint(inject, tmp_path)
        served.start()

        served.stop()

        assert not (tmp_path / ENDPOINT_FILE).exists()

    def test_stopping_leaves_a_newer_sessions_file(self, inject: _Recorder, tmp_path: Path) -> None:
        """Two sessions in one project: the newer one publishes over the older,
        and the older one exiting must not take the newer one's file with it."""
        older = SessionEndpoint(inject, tmp_path)
        older.start()
        newer = SessionEndpoint(inject, tmp_path)
        newer.start()

        older.stop()

        assert _published(tmp_path)["url"] == newer.url
        newer.stop()

    def test_stopping_without_a_file_is_fine(self, inject: _Recorder, tmp_path: Path) -> None:
        served = SessionEndpoint(inject, tmp_path)
        served.start()
        (tmp_path / ENDPOINT_FILE).unlink()

        served.stop()


class TestInjectIntoTheApp:
    async def test_an_idle_session_starts_a_turn_labelled_with_the_source(self) -> None:
        from apps.cli.screens.chat import ChatScreen

        app = _queue_app()
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            chat = app.screen
            assert isinstance(chat, ChatScreen)
            started: list[str] = []
            chat._run_agent = started.append  # type: ignore[method-assign]

            delivery = await app.inject_external_message("check MR 123", source="slack")

        assert delivery == "started"
        assert started == ["[via slack] check MR 123"]
        assert app.last_user_prompt == "[via slack] check MR 123"

    @pytest.mark.parametrize(
        ("mode", "delivery", "pending"),
        [("auto", "queued", (0, 1)), ("follow_up", "queued", (0, 1)), ("steer", "steered", (1, 0))],
    )
    async def test_a_running_session_queues_it(
        self, mode: Any, delivery: Delivery, pending: tuple[int, int]
    ) -> None:
        app = _queue_app()
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            barrier = asyncio.Event()
            app.agent_task = asyncio.create_task(barrier.wait())

            result = await app.inject_external_message(
                "check MR 123", source="slack", mode=mode, metadata={"ts": "17"}
            )

            assert result == delivery
            assert app.queue.pending_count() == pending
            queued = await (
                app.queue.drain_steering() if mode == "steer" else app.queue.drain_follow_up()
            )
            assert queued[0].metadata == {"ts": "17", "source": "slack"}
            barrier.set()
            await app.agent_task

    async def test_a_full_queue_is_a_refusal(self) -> None:
        from pydantic_deep.features.message_queue import MessageQueue

        app = _queue_app()
        app.queue = MessageQueue(max_pending=0)
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            barrier = asyncio.Event()
            app.agent_task = asyncio.create_task(barrier.wait())

            with pytest.raises(ExternalMessageRefused, match="full"):
                await app.inject_external_message("hi", source="ci")

            barrier.set()
            await app.agent_task

    async def test_a_running_session_without_a_queue_refuses(self) -> None:
        app = _queue_app()
        app.queue = None
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            barrier = asyncio.Event()
            app.agent_task = asyncio.create_task(barrier.wait())

            with pytest.raises(ExternalMessageRefused, match="no message queue"):
                await app.inject_external_message("hi", source="ci")

            barrier.set()
            await app.agent_task

    async def test_an_empty_message_is_refused(self) -> None:
        app = _queue_app()
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            with pytest.raises(ExternalMessageRefused, match="empty"):
                await app.inject_external_message("  ", source="ci")

    async def test_an_active_fork_refuses(self) -> None:
        app = _queue_app()
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.active_fork = object()  # type: ignore[assignment]
            with pytest.raises(ExternalMessageRefused, match="fork"):
                await app.inject_external_message("hi", source="ci")
            app.active_fork = None

    async def test_a_session_without_an_agent_refuses(self) -> None:
        from apps.cli.app import DeepApp

        app = DeepApp(model="test", version="0")
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            with pytest.raises(ExternalMessageRefused, match="no agent"):
                await app.inject_external_message("hi", source="ci")

    async def test_before_the_chat_screen_exists_it_refuses(self) -> None:
        app = _queue_app()
        with pytest.raises(ExternalMessageRefused, match="not ready"):
            await app.inject_external_message("hi", source="ci")

    async def test_external_steering_too_late_for_the_run_becomes_a_follow_up(self) -> None:
        """Steering that lands after the run's last model request would be
        dropped with a warning only the terminal shows; the sender never sees it."""
        from apps.cli.screens.chat import ChatScreen
        from pydantic_deep.features.message_queue import QueuedMessage

        app = _queue_app()
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            chat = app.screen
            assert isinstance(chat, ChatScreen)
            scheduled: list[str] = []
            run_turn = chat._run_agent
            chat._run_agent = scheduled.append  # type: ignore[method-assign]
            notes: list[str] = []
            app.notify = lambda msg, **_kw: notes.append(str(msg))  # type: ignore[method-assign]

            real_notify = chat._notify_degraded_mcp
            landed = {"done": False}

            def _land_late_steering() -> None:
                real_notify()
                if not landed["done"]:
                    landed["done"] = True
                    # The local one first: each drain returns one message.
                    app.queue._steering.append(QueuedMessage("typed too late", "steering"))
                    app.queue._steering.append(
                        QueuedMessage("check MR 123", "steering", metadata={"source": "slack"})
                    )

            chat._notify_degraded_mcp = _land_late_steering  # type: ignore[method-assign]

            run_turn("investigate the failing test")
            await _settle(pilot)

            assert app.queue.pending_count() == (0, 0)

        assert scheduled == ["[follow-up via slack] check MR 123"]
        assert any("1 steering message not delivered" in n for n in notes)

    async def test_late_external_steering_meeting_a_full_queue_is_reported(self) -> None:
        from apps.cli.screens.chat import ChatScreen
        from pydantic_deep.features.message_queue import MessageQueue, QueuedMessage

        app = _queue_app()
        app.queue = MessageQueue(max_pending=0)
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            chat = app.screen
            assert isinstance(chat, ChatScreen)
            notes: list[str] = []
            app.notify = lambda msg, **_kw: notes.append(str(msg))  # type: ignore[method-assign]
            real_notify = chat._notify_degraded_mcp

            def _land_late_steering() -> None:
                real_notify()
                app.queue._steering.append(
                    QueuedMessage("check MR 123", "steering", metadata={"source": "slack"})
                )

            chat._notify_degraded_mcp = _land_late_steering  # type: ignore[method-assign]

            chat._run_agent("investigate the failing test")
            await _settle(pilot)

        assert any("1 steering message not delivered" in n for n in notes)


class TestListeningApp:
    async def test_a_posted_message_starts_a_turn(self, tmp_path: Path) -> None:
        from apps.cli.screens.chat import ChatScreen

        app = _queue_app()
        app.working_dir = str(tmp_path)
        app._listen = True
        state_dir = tmp_path / ".pydantic-deep"
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            chat = app.screen
            assert isinstance(chat, ChatScreen)
            started: list[str] = []
            chat._run_agent = started.append  # type: ignore[method-assign]

            response = await asyncio.to_thread(
                _post, state_dir, {"text": "build is green", "source": "ci"}
            )

            assert response.status_code == 202
            assert response.json() == {"delivery": "started"}
            assert started == ["[via ci] build is green"]

        assert not (state_dir / ENDPOINT_FILE).exists()

    async def test_an_endpoint_that_cannot_start_is_reported(self, tmp_path: Path) -> None:
        app = _queue_app()
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        app.working_dir = str(blocker)
        app._listen = True
        notes: list[str] = []
        app.notify = lambda msg, **_kw: notes.append(str(msg))  # type: ignore[method-assign]
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()

        assert app._endpoint is None
        assert any("Could not start the session endpoint" in n for n in notes)
