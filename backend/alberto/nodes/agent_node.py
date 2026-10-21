"""Agent node (`create_agent`) and Deep Agent node (`create_deep_agent`).

Doc 2 §9. Both produce a compiled LangGraph graph used as a node inside the
workflow. The embedded agent does NOT carry its own checkpointer/store - the
top-level workflow graph owns durability, and LangGraph propagates it to subgraphs
at runtime (avoids nested-checkpointer conflicts and makes HITL interrupts bubble up).
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from alberto.engine.context import CompileContext
from alberto.engine.middleware_compiler import build_middleware
from alberto.engine.models import resolve_model
from alberto.engine.registry import NodeSpec, Port, register

log = logging.getLogger("forge.agent")


def _dedup_tools_by_name(tools: list) -> list:
    """Bind each tool NAME to the model at most once. `resolve_tool_ids` already de-dups by id (a
    tool shared across several sets is ONE record → one id, sent once), but tool names are NOT
    unique per project and the final list mixes sources (tools + knowledge + MCP + components), so
    two entries can still collide by name - which providers reject (OpenAI errors on a duplicate
    function name). Keep the first occurrence; drop later name-collisions with a warning."""
    seen: set[str] = set()
    out: list = []
    for t in tools:
        name = getattr(t, "name", None)
        if name is not None and name in seen:
            log.warning("agent tool name %r appears more than once; keeping the first, dropping the rest", name)
            continue
        if name is not None:
            seen.add(name)
        out.append(t)
    return out

# Forge's default output style: every agent reply renders as GitHub-Flavored Markdown
# (Feature 1 - structured responses). It lives in the system prompt, so it costs ~nothing
# per turn (and is cached by the Anthropic prompt-caching middleware). Opt out with
# config output_style="plain"; auto-skipped for structured-output agents (they emit JSON).
OUTPUT_STYLE = (
    "Format every reply as GitHub-Flavored Markdown so it renders cleanly: short "
    "paragraphs; `##`/`###` headings for sections; `-` or numbered lists; GFM tables for "
    "comparisons or structured data; fenced code blocks with a language hint for code; and "
    "**bold** for key terms. Keep the structure minimal - only as much as the answer needs "
    "- and never output raw HTML."
)


# When UI components are attached, structured data should be shown via a component (table/
# card/form), NOT a markdown table - so this variant drops the "GFM tables for structured
# data" clause to avoid competing with the widgets (audit B1).
OUTPUT_STYLE_WITH_COMPONENTS = (
    "Format every reply as GitHub-Flavored Markdown so it renders cleanly: short paragraphs; "
    "`##`/`###` headings; `-` or numbered lists; fenced code blocks with a language hint; and "
    "**bold** for key terms. For structured data (tables, cards, forms), prefer the available "
    "UI components over a markdown table. Keep structure minimal and never output raw HTML."
)


# Steer the agent to RENDER a fitting component instead of restating its data as prose, and to
# POSITION it correctly: calling a component tool returns a placeholder marker that the agent
# copies into its reply where the widget belongs - so the component is interleaved with the text
# in its natural place (mid-answer, after a heading, at the end) rather than always pinned to the
# top (which is what happens if placement is left to tool-call order). The last sentence is
# load-bearing: it makes clear components only PRESENT data, so the agent keeps using its
# retrieval/other tools normally - without it, the component guidance was competing with
# knowledge/FAQ search and the agent skipped it (audit Priority B + the KB regression). Only
# appended when config["components"] is non-empty.
COMPONENT_STYLE = (
    "You have UI components available as tools (their names match the components). If a "
    "component fits the data you want to show (a table, card, form, …), you MUST call that "
    "component tool with the data as its props INSTEAD of writing the same data as prose or a "
    "markdown table. The tool returns a placeholder marker like [[forge:component:ID]]; copy that "
    "marker verbatim into your reply at the exact position where the component should appear. You "
    "control the order - write text before and after the marker so the component lands in its "
    "natural place in the answer (in the middle, after a heading, or at the end), exactly as it "
    "would read in a normal reply. Never restate the component's contents as text. This governs "
    "only how you PRESENT data - keep using your other tools (search the knowledge base, look up "
    "FAQs, call APIs) normally to GET the information you need."
)


def _build_prompt(config: dict) -> str | None:
    # Static system prompt + Forge's default Markdown output style (+ component guidance when
    # components are attached). Dynamic prompts compile to a middleware (added later).
    base = (config.get("system_prompt") or "").strip()
    structured = (config.get("response_format") or {}).get("mode") == "structured"
    if structured or config.get("output_style") == "plain":
        return base or None
    has_components = bool(config.get("components"))
    style = OUTPUT_STYLE_WITH_COMPONENTS if has_components else OUTPUT_STYLE
    parts = ([base] if base else []) + [style]
    if has_components:
        parts.append(COMPONENT_STYLE)
    return "\n\n".join(parts).strip()


def _build_response_format(config: dict) -> Any:
    rf = config.get("response_format")
    if not rf or rf.get("mode") != "structured":
        return None
    # create_agent accepts a raw JSON-schema dict (auto provider/tool strategy).
    return rf.get("schema")


# deepagents' built-in `task`-tool guidance is a ~536-token essay injected into EVERY supervisor
# call. This concise replacement keeps the essential guidance at ~1/8th the tokens (a real per-turn
# cost lever for supervisors, which re-read their prompt every turn). Override via SubAgentMiddleware.
_TASK_TOOL_PROMPT = (
    "Use the `task` tool to delegate a self-contained subtask to one of the specialist subagents "
    "listed in its schema. Prefer it for multi-step work you can hand off wholesale, and dispatch "
    "independent subagents in parallel. You receive only each subagent's final result — not its "
    "intermediate steps — so give it a clear, complete instruction. Don't delegate trivial one-tool "
    "lookups; do those yourself."
)


def _ensure_safety_middleware(middleware: list[Any]) -> list[Any]:
    """Ensure mandatory safety limits are applied on every ReAct/subagent execution."""
    from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware

    from alberto.config import settings
    from alberto.engine.middleware_compiler import RepeatedToolCallMiddleware

    out = list(middleware)
    has_model_limit = False
    has_tool_limit = False
    has_repeated_guard = False

    for m in out:
        if isinstance(m, ModelCallLimitMiddleware):
            has_model_limit = True
            if m.run_limit is None or m.run_limit > settings.max_model_calls_per_run:
                m.run_limit = settings.max_model_calls_per_run
        elif isinstance(m, ToolCallLimitMiddleware) and getattr(m, "tool_name", None) is None:
            has_tool_limit = True
            if m.run_limit is None or m.run_limit > settings.max_tool_calls_per_run:
                m.run_limit = settings.max_tool_calls_per_run
        elif isinstance(m, RepeatedToolCallMiddleware):
            has_repeated_guard = True

    if not has_model_limit:
        out.append(ModelCallLimitMiddleware(run_limit=settings.max_model_calls_per_run, exit_behavior="error"))
    if not has_tool_limit:
        out.append(ToolCallLimitMiddleware(run_limit=settings.max_tool_calls_per_run, exit_behavior="error"))
    if not has_repeated_guard:
        out.append(RepeatedToolCallMiddleware(max_repeats=settings.max_repeated_no_progress_calls))

    return out


class MemoryRecallMiddleware(AgentMiddleware):
    """Milestone 2.2: Contextual recall hook integrating UnifiedMemoryManager with conversation turns.
    Retrieves active memories, graph facts, and knowledge using intelligent source routing,
    with scoped per-turn caching and strict lower-trust context assembly."""

    # Scoped per-turn cache: key -> (timestamp, context_block)
    _CACHE: dict[tuple, tuple[float, str]] = {}
    _CACHE_TTL: float = 60.0  # 60s per-turn lifetime
    _CACHE_MAX_ENTRIES: int = 512

    def __init__(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        import uuid

        self.tenant_id = tenant_id
        self.project_id = project_id
        self.user_id = user_id or "anonymous"
        self.turn_id = turn_id or str(uuid.uuid4())
        # Instance-level cache guaranteeing per-run / per-turn ownership
        self._local_cache: dict[tuple, tuple[float, str]] = {}

    @classmethod
    def invalidate_cache(
        cls,
        tenant_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Invalidate cache entries for a tenant/project/user or all entries."""
        if tenant_id and project_id:
            keys_to_del = []
            for k in list(cls._CACHE.keys()):
                if len(k) >= 2 and k[0] == tenant_id and k[1] == project_id:
                    if user_id is not None and len(k) >= 6:
                        if k[2] == user_id:
                            keys_to_del.append(k)
                    else:
                        keys_to_del.append(k)
            for k in keys_to_del:
                cls._CACHE.pop(k, None)
        else:
            cls._CACHE.clear()

    async def _fetch_memory_context(
        self,
        user_text: str,
        turn_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        if not user_text or len(user_text.strip()) < 3:
            return ""

        import hashlib
        import time

        from alberto.services.context_assembler import ContextAssembler
        from alberto.services.retrieval_policy import RetrievalPolicy

        effective_user = user_id or self.user_id
        effective_turn = turn_id or self.turn_id

        # 1. Deterministic source selection
        selected_sources = RetrievalPolicy.select_sources(user_text)
        if not selected_sources:
            log.info("Retrieval policy selected zero sources for query %r (general/chatter)", user_text[:40])
            return ""

        # 2. Check scoped per-turn cache (per-turn ownership with effective security scope)
        q_hash = hashlib.sha256(user_text.strip().lower().encode("utf-8")).hexdigest()[:16]
        cache_key = (
            self.tenant_id,
            self.project_id,
            effective_user,
            effective_turn,
            q_hash,
            tuple(sorted(selected_sources)),
        )
        now = time.monotonic()

        cached_entry = None
        if cache_key in self._CACHE:
            cached_entry = self._local_cache.get(cache_key) or self._CACHE.get(cache_key)
        else:
            self._local_cache.pop(cache_key, None)

        if cached_entry is not None:
            created_at, cached_block = cached_entry
            if (now - created_at) < self._CACHE_TTL:
                log.info(
                    "MemoryRecallMiddleware CACHE HIT for tenant=%s project=%s user=%s turn=%s query_hash=%s",
                    self.tenant_id,
                    self.project_id,
                    effective_user,
                    effective_turn,
                    q_hash,
                )
                return cached_block

        log.info(
            "MemoryRecallMiddleware CACHE MISS for tenant=%s project=%s user=%s turn=%s query_hash=%s sources=%s",
            self.tenant_id,
            self.project_id,
            effective_user,
            effective_turn,
            q_hash,
            selected_sources,
        )

        # 3. Retrieve evidence from UnifiedMemoryManager
        try:
            from alberto.db import SessionLocal
            from alberto.services.unified_memory import UnifiedMemoryManager

            async with SessionLocal() as session:
                hits = await UnifiedMemoryManager.recall(
                    session=session,
                    tenant_id=self.tenant_id,
                    project_id=self.project_id,
                    query=user_text.strip(),
                    sources=selected_sources,
                    top_k=5,
                )

            context_block = ContextAssembler.assemble_context(hits)

            # 4. Store in scoped cache
            if len(self._CACHE) >= self._CACHE_MAX_ENTRIES:
                oldest_key = min(self._CACHE.keys(), key=lambda k: self._CACHE[k][0])
                self._CACHE.pop(oldest_key, None)

            entry = (now, context_block)
            self._local_cache[cache_key] = entry
            self._CACHE[cache_key] = entry
            return context_block
        except Exception as e:
            log.warning("MemoryRecallMiddleware error: %s", e)
            return ""

    async def awrap_model_call(self, request, handler):
        messages = getattr(request, "messages", []) or []
        user_text = ""
        user_msg = None
        for m in reversed(messages):
            m_type = getattr(m, "type", None) or getattr(m, "role", None)
            if m_type in ("human", "user"):
                content = getattr(m, "content", "")
                user_text = content if isinstance(content, str) else str(content)
                user_msg = m
                break

        if user_text:
            # Per-turn ownership: user_msg stays the same object across multiple ReAct calls within one turn
            turn_scope = self.turn_id
            if user_msg is not None:
                turn_scope = getattr(user_msg, "id", None) or f"{self.turn_id}_{id(user_msg)}"
            context_block = await self._fetch_memory_context(user_text, turn_id=turn_scope)
            if context_block:
                from langchain_core.messages import SystemMessage

                sys_msg = getattr(request, "system_message", None)
                if sys_msg is not None:
                    new_content = f"{sys_msg.content}\n\n{context_block}"
                    request = request.override(system_message=SystemMessage(content=new_content))
                else:
                    base_prompt = getattr(request, "system_prompt", "") or ""
                    new_content = f"{base_prompt}\n\n{context_block}".strip()
                    request = request.override(system_message=SystemMessage(content=new_content))

        return await handler(request)

    def wrap_model_call(self, request, handler):
        import asyncio

        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        if loop and loop.is_running():
            return handler(request)
        return asyncio.run(self.awrap_model_call(request, lambda r: asyncio.sleep(0, handler(r))))


def _ensure_memory_middleware(middleware: list[Any], config: dict, ctx: CompileContext) -> list[Any]:
    """Ensure MemoryRecallMiddleware is attached unless memory is explicitly disabled."""
    out = list(middleware)
    if config.get("memory") is not False:
        if not any(isinstance(m, MemoryRecallMiddleware) for m in out):
            user_id = None
            if isinstance(ctx.end_user, dict):
                user_id = ctx.end_user.get("id") or ctx.end_user.get("user_id")
            elif isinstance(ctx.end_user, str):
                user_id = ctx.end_user
            out.append(MemoryRecallMiddleware(tenant_id=ctx.tenant_id, project_id=ctx.project_id, user_id=user_id))
    return out


def _wrap_tool_for_agent(
    inner_tool: Any,
    tool_id: str,
    agent_name: str,
    agent_cfg: dict,
    ctx: CompileContext,
) -> Any:
    """Enforce central ToolPolicyService evaluation on agent-initiated tool calls (GAP-SEC-01).

    Ensures caller identity, association verification, static entitlements, and runtime
    HITL approval checks (e.g. for delete or critical risk operations) are strictly evaluated
    before the agent executes the underlying tool.
    """
    from langchain.tools import ToolRuntime
    from langchain_core.tools import StructuredTool
    from alberto.tools.materialize import _accepts_runtime

    inner_coro = getattr(inner_tool, "coroutine", None)
    inner_func = getattr(inner_tool, "func", None)
    target_fn = inner_coro or inner_func
    pass_runtime = _accepts_runtime(target_fn) if target_fn else False

    async def _policy_wrapped(runtime: ToolRuntime | None = None, **kwargs):
        # Fast-pass for offline/unit tests where tenant_id and project_id are omitted
        if not getattr(ctx, "tenant_id", None) or not getattr(ctx, "project_id", None):
            if inner_coro is not None:
                return await (inner_coro(runtime=runtime, **kwargs) if pass_runtime else inner_coro(**kwargs))
            if inner_func is not None:
                return inner_func(runtime=runtime, **kwargs) if pass_runtime else inner_func(**kwargs)
            return await inner_tool.ainvoke(kwargs)

        user_context = ctx.end_user if isinstance(ctx.end_user, dict) else ({"id": str(ctx.end_user)} if ctx.end_user else {})
        state = getattr(runtime, "state", {}) if runtime else {}
        run_ctx = getattr(ctx, "run_context", {}) or {}
        exec_ctx = {
            "arguments": kwargs,
            "approval_id": state.get("approval_id") or run_ctx.get("approval_id"),
            "approved": state.get("approved") or state.get("human_approved") or run_ctx.get("approved"),
        }

        from alberto.services.tool_policy import ToolPolicyService
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            tool_id=tool_id,
            caller_type="subagent",
            caller_id=agent_name,
            subagent_config=agent_cfg,
            user_context=user_context,
            execution_context=exec_ctx,
        )

        if not decision.allowed:
            if decision.requires_approval:
                return (
                    f"Tool '{decision.tool_name or getattr(inner_tool, 'name', tool_id)}' requires Human-in-the-Loop approval before execution. "
                    f"Approval request created: {decision.approval_request_id}. Execution paused."
                )
            return f"Tool execution policy violation: {decision.reason}"

        if inner_coro is not None:
            return await (inner_coro(runtime=runtime, **kwargs) if pass_runtime else inner_coro(**kwargs))
        if inner_func is not None:
            return inner_func(runtime=runtime, **kwargs) if pass_runtime else inner_func(**kwargs)
        return await inner_tool.ainvoke(kwargs)

    def _policy_wrapped_sync(runtime: ToolRuntime | None = None, **kwargs):
        if not getattr(ctx, "tenant_id", None) or not getattr(ctx, "project_id", None):
            if inner_func is not None:
                return inner_func(runtime=runtime, **kwargs) if pass_runtime else inner_func(**kwargs)
            raise RuntimeError(f"Tool {getattr(inner_tool, 'name', tool_id)!r} does not support synchronous execution.")

        from alberto.services.tool_policy import ToolPolicyService
        allowed = ToolPolicyService.check_sync(
            ctx=ctx,
            tool_id=tool_id,
            caller_type="subagent",
            caller_id=agent_name,
            subagent_config=agent_cfg,
        )
        if not allowed:
            return f"Tool execution policy violation: tool '{getattr(inner_tool, 'name', tool_id)}' not allowed for agent '{agent_name}'."
        if inner_func is not None:
            return inner_func(runtime=runtime, **kwargs) if pass_runtime else inner_func(**kwargs)
        raise RuntimeError(f"Tool {getattr(inner_tool, 'name', tool_id)!r} does not support synchronous execution.")

    tool_name = getattr(inner_tool, "name", None) or tool_id
    tool_desc = getattr(inner_tool, "description", None) or ""
    tool_schema = getattr(inner_tool, "args_schema", None)

    return StructuredTool.from_function(
        func=_policy_wrapped_sync if inner_func is not None else None,
        coroutine=_policy_wrapped,
        name=tool_name,
        description=tool_desc,
        args_schema=tool_schema,
    )


def _resolve_and_secure_agent_tools(
    tool_refs: list[str] | None,
    toolsets: list[str] | None,
    agent_name: str,
    agent_cfg: dict,
    ctx: CompileContext,
) -> list[Any]:
    ids = ctx.resolve_tool_ids(tool_refs, toolsets)
    out: list[Any] = []
    for tid in ids:
        raw_t = ctx.tool_registry.get(tid)
        if raw_t is not None:
            out.append(_wrap_tool_for_agent(raw_t, tid, agent_name, agent_cfg, ctx))
    return out


def build_subagents(subagents_cfg: list[dict], ctx: CompileContext, default_model: Any = None) -> list[dict]:
    """Convert subagent configs to the SubAgent dict shape SubAgentMiddleware expects.

    Standalone SubAgentMiddleware (our lean deep_agent, see agent_factory) REQUIRES each subagent to
    carry `model` and `tools` - create_deep_agent used to fill those in - and deepagents re-resolves
    a *string* model via init_chat_model WITHOUT our injected provider key, so we always set a
    RESOLVED model object (defaulting to the parent deep_agent's model) and a concrete tools list.
    `system_prompt` is always set (deepagents wraps it). `workflow_ref` subagents are the still-
    unwired subworkflow phase.
    """
    out: list[dict] = []
    for sa in subagents_cfg or []:
        if "workflow_ref" in sa:
            continue  # TODO(phase: subworkflow): wrap compiled workflow as CompiledSubAgent
        name = sa["name"]
        secured_tools = _resolve_and_secure_agent_tools(sa.get("tools"), sa.get("toolsets"), name, sa, ctx)
        spec: dict[str, Any] = {
            "name": name,
            "description": sa.get("description", ""),
            "system_prompt": sa.get("system_prompt") or sa.get("description") or f"You are the {name} agent.",
            "tools": _dedup_tools_by_name(secured_tools),
            "model": resolve_model(sa["model"], ctx) if sa.get("model") else (default_model or resolve_model(None, ctx)),
        }
        sub_mw = build_middleware(sa["middleware"], ctx) if sa.get("middleware") else []
        spec["middleware"] = _ensure_safety_middleware(sub_mw)
        out.append(spec)
    return out


def _maybe_add_prompt_caching(stack: list[dict], config: dict, ctx: CompileContext) -> list[dict]:
    """Prepend Anthropic prompt-caching middleware for Anthropic-model agents (cost lever),
    unless already present or disabled. Best-effort: only when langchain-anthropic exists."""
    import importlib.util

    from alberto.config import settings

    if not settings.default_anthropic_prompt_caching:
        return stack
    model_ref = config.get("model") or getattr(ctx, "default_model", "") or ""
    if not (isinstance(model_ref, str) and model_ref.startswith("anthropic")):
        return stack
    if any((m or {}).get("type") == "anthropic_prompt_caching" for m in stack):
        return stack
    if importlib.util.find_spec("langchain_anthropic") is None:
        return stack
    return [{"type": "anthropic_prompt_caching", "config": {}}, *stack]


def _clamp(value, n: int = 300):
    """Bound an end_user value's size before it enters the prompt (avoid bloat/abuse)."""
    if isinstance(value, str):
        return value[:n]
    if isinstance(value, list):
        return [_clamp(v, n) for v in value[:20]]
    if isinstance(value, dict):
        return {str(k)[:60]: _clamp(v, n) for k, v in list(value.items())[:20]}
    return value


def _end_user_block(end_user: dict) -> str:
    """A generic identity-awareness block. Only a whitelisted, size-clamped subset of the
    (untrusted-shaped) end_user is embedded, re-serialized so the JSON stays well-formed
    (audit L4). The withhold-restriction sentence is added ONLY when the user actually carries
    roles/entitlements - an unscoped prohibition with no entitlement list made the model
    over-refuse general KB/FAQ answers ("I don't have that information") (audit Priority A)."""
    import json as _json

    safe = {
        k: _clamp(end_user[k])
        for k in ("id", "display_name", "email", "roles", "entitlements", "attributes")
        if end_user.get(k) not in (None, "", [], {})
    }
    if not safe:
        return ""
    eu = _json.dumps(safe, default=str, ensure_ascii=False)
    line = (
        "[END USER] You are assisting this authenticated end user, provided by the host "
        f"application - treat it as authoritative: {eu}."
    )
    if safe.get("roles") or safe.get("entitlements"):
        line += (
            " General product, FAQ, and knowledge-base information is available to everyone - "
            "always answer it. Only withhold data that is specific to OTHER users or accounts "
            "this user is not entitled to see or act on."
        )
    return line


def _dynamic_field_middleware(config: dict, ctx: CompileContext, base_prompt: str | None) -> list:
    """Compile the agent node's `dynamic_model` / `dynamic_prompt` blocks - both exposed in the
    UI but previously unwired (audit F9) - into middleware.

    - dynamic_model reuses the proven `dynamic_model_by_state` builder (switch model by a
      state expression).
    - dynamic_prompt renders the FIRST matching rule's prompt (with `{{state.*}}` tokens) as
      the system prompt per model call, falling back to the node's static prompt when no rule
      matches - so enabling it with no matching rule is behavior-neutral."""
    extra: list = []

    dm = config.get("dynamic_model") or {}
    if dm.get("enabled") and dm.get("rules"):
        extra += build_middleware(
            [{"type": "dynamic_model_by_state", "config": {"rules": dm["rules"], "default": dm.get("default")}}],
            ctx,
        )

    dp = config.get("dynamic_prompt") or {}
    rules = dp.get("rules") or []
    if dp.get("enabled") and rules:
        from langchain.agents.middleware import dynamic_prompt as _dynamic_prompt

        from alberto.auth_providers.templates import render_template
        from alberto.engine.expressions import ExpressionError, eval_truthy

        fallback = base_prompt or ""

        @_dynamic_prompt
        def _prompt(request):  # type: ignore[no-untyped-def]
            state = dict(getattr(request, "state", {}) or {})
            for r in rules:
                text = r.get("prompt")
                if not text:
                    continue
                when = r.get("when")
                try:
                    if not when or eval_truthy(when, state):
                        rendered = render_template(text, {"state": state}) if isinstance(text, str) else text
                        return str(rendered) if rendered is not None else fallback
                except ExpressionError:
                    continue
            return fallback

        extra.append(_prompt)

    return extra


def _common_kwargs(config: dict, ctx: CompileContext) -> dict:
    agent_name = config.get("name") or "agent"
    tools = list(_resolve_and_secure_agent_tools(config.get("tools"), config.get("toolsets"), agent_name, config, ctx))
    # Built-in knowledge access (RAG / Q&A) attached straight to the agent via its
    # `knowledge` config - no separate Tool row needed (see tools/builtin.py).
    if config.get("knowledge"):
        from alberto.tools.builtin import build_knowledge_capability_tools
        tools += build_knowledge_capability_tools(config["knowledge"], ctx)
    # Agent-scoped MCP server access: attach each selected server's enabled tools
    # (pre-loaded by the runtime assembler into ctx.mcp_tools_by_client; native MCP tools).
    for cid in config.get("mcp_servers", []) or []:
        tools += (getattr(ctx, "mcp_tools_by_client", None) or {}).get(cid, [])
    # User-defined UI components exposed as widget-tools (Feature 2): the agent "renders"
    # one by calling it; the client draws the saved template from the props it passes.
    tools += list(ctx.components_for(config.get("components", [])))
    # Final guard: exactly one function name per model call, whatever the source mix.
    tools = _dedup_tools_by_name(tools)
    stack = (ctx.project_default_mw or []) + (config.get("middleware") or [])
    stack = _maybe_add_prompt_caching(stack, config, ctx)
    middleware = build_middleware(stack, ctx)
    model = resolve_model(config.get("model"), ctx, config.get("model_params"))

    common: dict[str, Any] = {"model": model, "tools": tools, "middleware": middleware}
    prompt = _build_prompt(config)
    # Identity awareness: if the run acts for an end user, append a generic context block so
    # the agent knows who it's helping and to stay within their entitlements. Appended last,
    # so the (cacheable) instructions prefix is unchanged; only this per-user suffix varies.
    end_user = getattr(ctx, "end_user", None)
    if end_user:
        eu_block = _end_user_block(end_user)
        if eu_block:
            prompt = f"{prompt}\n\n{eu_block}" if prompt else eu_block
    if prompt:
        common["system_prompt"] = prompt
    # Wire the dynamic_model / dynamic_prompt config blocks (append after the static stack so
    # a matching rule overrides the base at call time). base_prompt = the fully-built static
    # prompt so a non-matching dynamic_prompt run reproduces the static behavior exactly.
    dynamic_mw = _dynamic_field_middleware(config, ctx, prompt)
    if dynamic_mw:
        common["middleware"] = list(middleware) + dynamic_mw
    rf = _build_response_format(config)
    if rf is not None:
        common["response_format"] = rf
    if config.get("name"):
        common["name"] = config["name"]
    return common


def _resolve_config(config: dict, ctx: CompileContext) -> dict:
    """If the node mirrors a saved agent (`agent_ref`), the live preset drives it - so
    edits in the Agents tab take effect without re-saving the workflow. Falls back to the
    node's own (snapshot) config when the preset is missing/unresolved."""
    ref = config.get("agent_ref")
    if ref:
        preset = (getattr(ctx, "agent_presets", None) or {}).get(ref)
        if preset:
            return dict(preset)
    return config


def agent_factory(config: dict, ctx: CompileContext):
    config = _resolve_config(config, ctx)
    common = _common_kwargs(config, ctx)
    common["middleware"] = _ensure_memory_middleware(
        _ensure_safety_middleware(common.get("middleware") or []), config, ctx
    )

    from langchain.agents import create_agent

    if config.get("flavor") == "deep_agent":
        # A deep_agent is `create_agent` + only the deepagents harness pieces the operator opts
        # into (planning / filesystem / subagents). We do NOT use `create_deep_agent`, which always
        # bundles the FULL harness (write_todos + filesystem + a general-purpose subagent + a large
        # base prompt) - that overhead made a simple lookup ~6x the tokens of a lean agent. Each
        # piece is added only when its config toggle is on, exactly like attaching a tool.
        try:
            from deepagents import SubAgentMiddleware
            from deepagents.backends import StateBackend
        except ImportError as e:  # pragma: no cover - deepagents is a core dep
            raise ImportError(
                "deep_agent flavor needs `deepagents` (a core dependency - reinstall with "
                "`pip install -e .`)."
            ) from e

        # Backend for the filesystem / subagent middleware: a sandbox if configured, else the
        # default in-memory (thread-scoped) state backend - which carries NO shell `execute` tool.
        backend = ctx.sandbox_backend_for(config.get("sandbox", {}) or {}) or StateBackend()

        middleware = list(common.get("middleware") or [])
        if config.get("planning"):  # write_todos planner (off by default - pure token overhead)
            from langchain.agents.middleware import TodoListMiddleware
            middleware.append(TodoListMiddleware())
        fs = config.get("filesystem") or {}
        if fs.get("enabled") or (fs.get("backend") and fs.get("backend") != "none"):
            from deepagents.middleware import FilesystemMiddleware
            middleware.append(FilesystemMiddleware(backend=backend))
        # Deep-agent skills (agent-skills source paths): wire as SkillsMiddleware - the SAME
        # middleware create_deep_agent uses - so deep_agent NODES keep the skills capability under
        # the lean create_agent path (backend-backed, so skill files load from the configured store).
        if config.get("skills"):
            from deepagents.middleware.skills import SkillsMiddleware
            middleware.append(SkillsMiddleware(backend=backend, sources=list(config["skills"])))
        subagents = build_subagents(config.get("subagents", []), ctx, default_model=common["model"])
        if subagents:
            middleware.append(SubAgentMiddleware(backend=backend, subagents=subagents, system_prompt=_TASK_TOOL_PROMPT))

        kwargs: dict[str, Any] = dict(common)
        kwargs["middleware"] = middleware
        raw_agent = create_agent(**kwargs)
    else:
        raw_agent = create_agent(**common)

    task_prompt = config.get("task_prompt") or config.get("prompt")
    rf = config.get("response_format") or {}
    output_key = config.get("output_key") or (rf.get("output_key") if rf.get("mode") == "structured" else None)

    if not task_prompt and not output_key:
        return raw_agent

    async def _pipeline_node(state: dict) -> dict:
        from langchain_core.messages import HumanMessage
        from alberto.auth_providers.templates import render_template

        agent_state = dict(state or {})
        if task_prompt:
            rendered = render_template(task_prompt, {"state": dict(state or {})})
            if rendered is not None and not isinstance(rendered, str):
                rendered = str(rendered)
            if rendered:
                existing_msgs = list(agent_state.get("messages") or [])
                agent_state["messages"] = [*existing_msgs, HumanMessage(content=rendered)]

        result = await raw_agent.ainvoke(agent_state)
        out: dict[str, Any] = dict(result or {})
        if output_key:
            parsed = _extract_structured_data(result)
            if parsed is not None:
                out[output_key] = parsed
        return out

    return _pipeline_node


def _extract_structured_data(res: dict) -> Any:
    """Extract structured data from an agent execution result dictionary."""
    msgs = res.get("messages") or []
    if not msgs:
        return None
    last = msgs[-1]
    sr = getattr(last, "structured_response", None)
    if sr is not None:
        return sr
    content = getattr(last, "content", None)
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        text = content.strip()
        import json
        import re

        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            text = m.group(1).strip()
        try:
            return json.loads(text)
        except Exception:
            pass
    for tc in getattr(last, "tool_calls", []) or []:
        args = tc.get("args")
        if isinstance(args, dict):
            return args
    return None


def _summary(config: dict) -> list[str]:
    model = config.get("model", "-")
    n_tools = len(config.get("tools", []) or [])
    n_mw = len([m for m in (config.get("middleware") or []) if m.get("enabled", True)])
    flavor = config.get("flavor", "agent")
    line2 = f"{n_tools} tools · {n_mw} middleware"
    n_comp = len(config.get("components", []) or [])
    if n_comp:
        line2 += f" · {n_comp} widget{'s' if n_comp != 1 else ''}"
    k = config.get("knowledge") or {}
    kbits = [name for name, key in (("RAG", "rag"), ("Q&A", "qa")) if (k.get(key) or {}).get("enabled")]
    if kbits:
        line2 += " · KB " + "+".join(kbits)
    n_mcp = len(config.get("mcp_servers", []) or [])
    if n_mcp:
        line2 += f" · MCP {n_mcp}"
    if flavor == "deep_agent":
        line2 += f" · subagents {len(config.get('subagents', []) or [])}"
    rf = config.get("response_format") or {}
    out_k = config.get("output_key") or (rf.get("output_key") if rf.get("mode") == "structured" else None)
    if out_k:
        line2 += f" · out: {out_k}"
    return [str(model), line2]


_ports = (
    [Port(id="in", io_type="messages", direction="in")],
    [Port(id="out", io_type="messages", direction="out")],
)

register(
    NodeSpec(
        type="agent",
        schema_id="forge/nodes/agent",
        input_ports=_ports[0],
        output_ports=_ports[1],
        factory=agent_factory,
        allows_cycle=True,
        category="agents",
        label="Agent",
        description="ReAct tool loop",
        summarize=_summary,
    )
)

register(
    NodeSpec(
        type="deep_agent",
        schema_id="forge/nodes/agent",
        input_ports=_ports[0],
        output_ports=_ports[1],
        factory=agent_factory,
        allows_cycle=True,
        category="agents",
        label="Deep Agent",
        description="Planning + subagents harness",
        summarize=_summary,
    )
)
