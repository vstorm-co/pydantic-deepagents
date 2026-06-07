"""Tests for the desktop launcher's non-GUI plumbing."""

from __future__ import annotations

from apps.desktop.launcher import (
    find_free_port,
    start_gateway_thread,
    wait_for_health,
)
from apps.gateway.auth import generate_token


def test_find_free_port() -> None:
    port = find_free_port()
    assert isinstance(port, int)
    assert 1024 < port < 65536


def test_wait_for_health_times_out_for_dead_port() -> None:
    # An unused port never answers — wait returns False within the timeout.
    dead = find_free_port()
    assert wait_for_health("127.0.0.1", dead, timeout=0.5) is False


def test_gateway_thread_serves_health() -> None:
    host = "127.0.0.1"
    port = find_free_port(host)
    token = generate_token()
    thread = start_gateway_thread(host, port, token)
    try:
        assert wait_for_health(host, port, timeout=10.0) is True
    finally:
        # Daemon thread; it is torn down with the process.
        assert thread.daemon is True
