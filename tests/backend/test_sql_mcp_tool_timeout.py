import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.tools import StructuredTool
from alberto.tools.sql import execute_sql, SqlToolError
from alberto.tools.mcp import _wrap_with_timeout


@pytest.mark.asyncio
async def test_sql_tool_timeout():
    with patch("alberto.tools.sql._engine_for") as mock_engine_for:
        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"
        mock_engine_for.return_value = mock_engine

        with patch("alberto.tools.sql.async_sessionmaker") as mock_sm:
            mock_session = MagicMock()
            mock_session.begin = AsyncMock()
            mock_session.execute = AsyncMock()
            mock_session.rollback = AsyncMock()
            mock_session.close = AsyncMock()

            async def slow_stream(*args, **kwargs):
                await asyncio.sleep(2.0)
                return MagicMock()

            mock_session.stream = slow_stream
            # sm is called: sm() -> context manager
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=None)
            mock_sm.return_value = MagicMock(return_value=ctx)

            cfg = {
                "query": "SELECT * FROM large_table",
                "connection_url": "postgresql+asyncpg://user:pass@localhost:5432/db",
                "timeout_seconds": 0.1,
            }

            with pytest.raises(SqlToolError) as exc_info:
                await execute_sql(cfg, {}, tenant_id="t1", project_id="p1")

            assert "timed out" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_mcp_tool_timeout():
    async def slow_mcp_func(**kwargs):
        await asyncio.sleep(2.0)
        return "late answer"

    base_tool = StructuredTool.from_function(
        coroutine=slow_mcp_func,
        name="slow_mcp_calc",
        description="Performs slow computation",
    )

    wrapped_tool = _wrap_with_timeout(base_tool, timeout_seconds=0.1)

    result = await wrapped_tool.ainvoke({"input": "test"})

    assert "slow_mcp_calc" in result
    assert "timed out" in result.lower()
