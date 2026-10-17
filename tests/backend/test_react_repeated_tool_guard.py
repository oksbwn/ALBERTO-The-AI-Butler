import pytest
from alberto.engine.middleware_compiler import RepeatedToolCallMiddleware, RepeatedToolCallLimitError


class FakeRequest:
    def __init__(self, name: str, args: dict):
        self.tool_call = {"name": name, "args": args}


class FakeResult:
    def __init__(self, content: str, status: str = "success"):
        self.content = content
        self.status = status


@pytest.mark.asyncio
async def test_repeated_tool_call_middleware_detects_loop():
    mw = RepeatedToolCallMiddleware(max_repeats=3)
    req = FakeRequest("fetch_user", {"id": "123"})

    async def failing_handler(r):
        return FakeResult("Error: connection refused", status="error")

    # 1st call: error recorded, count = 1
    await mw.awrap_tool_call(req, failing_handler)
    # 2nd call: error recorded, count = 2
    await mw.awrap_tool_call(req, failing_handler)
    
    # 3rd call: triggers RepeatedToolCallLimitError
    with pytest.raises(RepeatedToolCallLimitError) as exc_info:
        await mw.awrap_tool_call(req, failing_handler)
    
    assert "repeated unsuccessful tool call" in str(exc_info.value)
    assert "fetch_user" in str(exc_info.value)


@pytest.mark.asyncio
async def test_repeated_tool_call_middleware_allows_progress():
    mw = RepeatedToolCallMiddleware(max_repeats=3)

    async def ok_handler(r):
        page = r.tool_call["args"]["page"]
        return FakeResult(f"items for page {page}")

    # Tool call with changing args (progress / pagination)
    await mw.awrap_tool_call(FakeRequest("query_db", {"page": 1}), ok_handler)
    await mw.awrap_tool_call(FakeRequest("query_db", {"page": 2}), ok_handler)
    await mw.awrap_tool_call(FakeRequest("query_db", {"page": 3}), ok_handler)
    await mw.awrap_tool_call(FakeRequest("query_db", {"page": 4}), ok_handler)
    # No error raised because arguments changed
    assert True


@pytest.mark.asyncio
async def test_repeated_tool_call_middleware_success_resets_streak():
    mw = RepeatedToolCallMiddleware(max_repeats=3)
    req = FakeRequest("poke", {})

    async def failing_handler(r):
        return FakeResult("Error: transient", status="error")

    async def success_handler(r):
        return FakeResult("Success: updated state")

    # 2 failing calls
    await mw.awrap_tool_call(req, failing_handler)
    await mw.awrap_tool_call(req, failing_handler)

    # 1 successful call with meaningful progress
    await mw.awrap_tool_call(req, success_handler)

    # Streak is reset! A subsequent failure starts at count 1, so does not raise
    await mw.awrap_tool_call(req, failing_handler)
    assert True
