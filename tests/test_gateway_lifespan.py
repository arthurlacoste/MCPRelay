from __future__ import annotations

import asyncio
import logging

import mcp_gateway


def test_builtin_skill_install_failure_does_not_block_gateway_startup(monkeypatch, caplog):
    calls: list[str] = []

    def fail_install():
        raise OSError("disk full")

    async def start(server):
        calls.append("start")

    async def close():
        calls.append("close")

    async def exercise_lifespan():
        async with mcp_gateway.gateway_lifespan(object()):
            calls.append("yield")

    monkeypatch.setattr(mcp_gateway, "install_builtin_skills", fail_install)
    monkeypatch.setattr(mcp_gateway.proxy_manager, "start", start)
    monkeypatch.setattr(mcp_gateway.proxy_manager, "close", close)

    with caplog.at_level(logging.ERROR, logger=mcp_gateway.__name__):
        asyncio.run(exercise_lifespan())

    assert calls == ["start", "yield", "close"]
    assert "Failed to install builtin skills" in caplog.text
    assert "disk full" in caplog.text



def test_builtin_skill_install_timeout_does_not_block_startup(monkeypatch, caplog):
    calls: list[str] = []

    async def timeout(awaitable, timeout):
        awaitable.close()
        raise TimeoutError

    async def start(server):
        calls.append("start")

    async def close():
        calls.append("close")

    async def exercise_lifespan():
        async with mcp_gateway.gateway_lifespan(object()):
            calls.append("yield")

    monkeypatch.setattr(mcp_gateway.asyncio, "wait_for", timeout)
    monkeypatch.setattr(mcp_gateway.proxy_manager, "start", start)
    monkeypatch.setattr(mcp_gateway.proxy_manager, "close", close)

    with caplog.at_level(logging.ERROR, logger=mcp_gateway.__name__):
        asyncio.run(exercise_lifespan())

    assert calls == ["start", "yield", "close"]
    assert "timed out" in caplog.text
