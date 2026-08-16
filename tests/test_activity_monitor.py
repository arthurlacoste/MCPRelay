import asyncio

from fastmcp import Client, FastMCP

from realtime_calls import RealtimeCallStore


def _calls_by_tool(store):
    return {item["tool"]: item for item in store.snapshot()["calls"]}


def test_tool_activity_gets_stable_auto_conversation_for_mcp_session():
    from activity_monitor import GateActivityMiddleware

    store = RealtimeCallStore()
    mcp = FastMCP("activity-test")

    @mcp.tool
    def first() -> str:
        return "one"

    @mcp.tool
    def second() -> str:
        return "two"

    mcp.add_middleware(GateActivityMiddleware(store))

    async def scenario():
        async with Client(mcp) as client:
            await client.call_tool("first", {})
            await client.call_tool("second", {})

    asyncio.run(scenario())

    calls = _calls_by_tool(store)
    assert calls["first"]["status"] == "success"
    assert calls["second"]["status"] == "success"
    assert calls["first"]["conversation_id"].startswith("conv_auto_")
    assert calls["first"]["conversation_id"] == calls["second"]["conversation_id"]
    assert calls["first"]["session_ref"] == calls["second"]["session_ref"]
    assert calls["first"]["request_id"] != calls["second"]["request_id"]


def test_explicit_conversation_id_replaces_auto_id_for_following_calls():
    from activity_monitor import GateActivityMiddleware

    store = RealtimeCallStore()
    mcp = FastMCP("activity-test")

    @mcp.tool
    def bind(conversation_id: str | None = None) -> str:
        return conversation_id or "none"

    @mcp.tool
    def follow() -> str:
        return "ok"

    mcp.add_middleware(GateActivityMiddleware(store))

    async def scenario():
        async with Client(mcp) as client:
            await client.call_tool("follow", {})
            await client.call_tool("bind", {"conversation_id": "conv-explicit"})
            await client.call_tool("follow", {})

    asyncio.run(scenario())

    follow_calls = [item for item in store.snapshot()["calls"] if item["tool"] == "follow"]
    bind_call = next(item for item in store.snapshot()["calls"] if item["tool"] == "bind")
    assert bind_call["conversation_id"] == "conv-explicit"
    assert any(item["conversation_id"].startswith("conv_auto_") for item in follow_calls)
    assert any(item["conversation_id"] == "conv-explicit" for item in follow_calls)


def test_generated_conversation_id_from_tool_result_becomes_session_conversation():
    from activity_monitor import GateActivityMiddleware

    store = RealtimeCallStore()
    mcp = FastMCP("activity-test")

    @mcp.tool
    def conversation_start() -> dict:
        return {"conversation_id": "conv-generated"}

    @mcp.tool
    def follow() -> str:
        return "ok"

    mcp.add_middleware(GateActivityMiddleware(store))

    async def scenario():
        async with Client(mcp) as client:
            await client.call_tool("conversation_start", {})
            await client.call_tool("follow", {})

    asyncio.run(scenario())

    calls = _calls_by_tool(store)
    assert calls["conversation_start"]["conversation_id"] == "conv-generated"
    assert calls["follow"]["conversation_id"] == "conv-generated"


def test_discovery_call_is_displayed_as_real_downstream_tool():
    from activity_monitor import GateActivityMiddleware

    store = RealtimeCallStore()
    mcp = FastMCP("activity-test")

    @mcp.tool
    def mcp_tool_call(server_name: str, tool_name: str, arguments: dict | None = None) -> dict:
        return {"ok": True}

    mcp.add_middleware(GateActivityMiddleware(store))

    async def scenario():
        async with Client(mcp) as client:
            await client.call_tool("mcp_tool_call", {
                "server_name": "chrome-devtools",
                "tool_name": "navigate_page",
                "arguments": {"url": "https://example.test"},
            })

    asyncio.run(scenario())

    call = store.snapshot()["calls"][0]
    assert call["tool"] == "chrome-devtools.navigate_page"
    assert call["kind"] == "mcp"
    assert "https://example.test" not in repr(call)


def test_command_state_activity_keeps_parent_execution_id():
    from activity_monitor import GateActivityMiddleware

    store = RealtimeCallStore()
    mcp = FastMCP("activity-test")

    @mcp.tool
    def get_command_state(execution_id: str) -> dict:
        return {"execution_id": execution_id, "status": "success"}

    mcp.add_middleware(GateActivityMiddleware(store))

    async def scenario():
        async with Client(mcp) as client:
            await client.call_tool("get_command_state", {"execution_id": "exec-parent"})

    asyncio.run(scenario())
    call = store.snapshot()["calls"][0]
    assert call["parent_execution_id"] == "exec-parent"
    assert call["preview"] == "exec-parent"


def test_resources_and_prompts_are_monitored_as_semantic_activity():
    from activity_monitor import GateActivityMiddleware

    store = RealtimeCallStore()
    mcp = FastMCP("activity-test")

    @mcp.resource("data://status")
    def status() -> str:
        return "ready"

    @mcp.prompt
    def greet(name: str) -> str:
        return f"Hello {name}"

    mcp.add_middleware(GateActivityMiddleware(store))

    async def scenario():
        async with Client(mcp) as client:
            await client.read_resource("data://status")
            await client.get_prompt("greet", {"name": "Arthur"})

    asyncio.run(scenario())

    calls = store.snapshot()["calls"]
    resource = next(item for item in calls if item["kind"] == "resource")
    prompt = next(item for item in calls if item["kind"] == "prompt")
    assert resource["tool"] == "resource:data://status"
    assert prompt["tool"] == "prompt:greet"
    assert resource["conversation_id"] == prompt["conversation_id"]
    assert "Arthur" not in repr(prompt)


def test_excluded_run_command_receives_auto_conversation_without_duplicate_activity():
    from activity_monitor import GateActivityMiddleware

    store = RealtimeCallStore()
    mcp = FastMCP("activity-test")

    @mcp.tool
    def run_command(command: str, conversation_id: str | None = None) -> dict:
        return {"conversation_id": conversation_id}

    mcp.add_middleware(GateActivityMiddleware(store))

    async def scenario():
        async with Client(mcp) as client:
            result = await client.call_tool("run_command", {"command": "echo ok"})
            return result.structured_content

    result = asyncio.run(scenario())

    assert result["conversation_id"].startswith("conv_auto_")
    assert store.snapshot()["calls"] == []


def test_cancelled_tool_activity_is_marked_cancelled():
    import asyncio
    from types import SimpleNamespace

    from activity_monitor import GateActivityMiddleware

    store = RealtimeCallStore()
    middleware = GateActivityMiddleware(store)
    context = SimpleNamespace(
        message=SimpleNamespace(name="cancel_me", arguments={}),
        fastmcp_context=None,
    )

    async def cancelled(_context):
        raise asyncio.CancelledError

    async def scenario():
        try:
            await middleware.on_call_tool(context, cancelled)
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    call = store.snapshot()["calls"][0]
    assert call["tool"] == "cancel_me"
    assert call["status"] == "cancelled"
    assert call["finished_at"] is not None


def test_missing_mcp_session_does_not_break_tool_activity():
    from types import SimpleNamespace

    from activity_monitor import GateActivityMiddleware

    class NoSessionContext:
        @property
        def session_id(self):
            raise RuntimeError("no session")

        @property
        def request_id(self):
            raise RuntimeError("no request")

        @property
        def client_id(self):
            return None

    store = RealtimeCallStore()
    middleware = GateActivityMiddleware(store)
    context = SimpleNamespace(
        message=SimpleNamespace(name="skills_search", arguments={}),
        fastmcp_context=NoSessionContext(),
    )

    async def call_next(_context):
        return SimpleNamespace(structured_content=None)

    asyncio.run(middleware.on_call_tool(context, call_next))

    call = store.snapshot()["calls"][0]
    assert call["status"] == "success"
    assert call["conversation_id"] is None
    assert call["session_ref"] is None
    assert call["request_id"] is None
