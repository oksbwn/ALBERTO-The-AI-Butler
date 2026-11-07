"""Forge Assistant - a meta-agent whose tools are the Forge platform itself.

It can inspect a project and *build* into it: create tools, auth providers, Q&A,
knowledge, and workflows; and explain how the pieces fit together. It runs with the
project's own provider key (resolved from the secret store) and streams its narration
token-by-token over SSE, emitting `tool` events as it performs each action.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import select

from alberto.agents.automation_manager.tools import _assistant_model_ref, _default_agent_model
from alberto.agents.base import load_agent_markdown as _load_agent_md
from alberto.agents.butler.tools import build_assistant_tools
from alberto.config import settings
from alberto.db.base import SessionLocal
from alberto.engine.models import resolve_model
from alberto.models import Project
from alberto.services.runtime import build_compile_context
from alberto.util.serialize import content_to_text, jsonable

log = logging.getLogger("alberto.services.assistant")

SYSTEM_PROMPT = _load_agent_md(Path(__file__).resolve().parents[1] / "agents" / "butler", "deep_prompt.md")

# The orchestrating assistant juggles ~19 tools and a long policy prompt - small models
# routinely ignore parameters like review_before_reply. Prefer the provider's strong
# model for the assistant itself (workflow agents keep the cheaper project default).
# Skills directory for assistant capabilities
_SKILLS_DIR = Path(__file__).resolve().parents[1] / "assistant_skills"


def _compact_tool_result(res: Any, max_chars: int = 2500) -> str:
    """Cap and compact tool result content fed back to the LLM to prevent GPU KV-cache OOM."""
    s = str(res)
    if len(s) <= max_chars:
        return s
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], list):
                inner_list = data["result"]
                if inner_list and isinstance(inner_list[0], dict) and "text" in inner_list[0]:
                    try:
                        inner_data = json.loads(inner_list[0]["text"])
                        if isinstance(inner_data, dict):
                            if "entities" in inner_data and isinstance(inner_data["entities"], list):
                                inner_data["entities"] = inner_data["entities"][:10]
                            if "automations" in inner_data and isinstance(inner_data["automations"], list):
                                inner_data["automations"] = inner_data["automations"][:3]
                            inner_list[0]["text"] = json.dumps(inner_data)
                    except Exception:
                        pass
                data["result"] = inner_list[:5]
                compacted = json.dumps(data)
                if len(compacted) <= max_chars:
                    return compacted
    except Exception:
        pass
    return s[:max_chars] + f"\n... [output truncated to {max_chars} chars for model context]"


class AssistantService:
    @staticmethod
    async def _build_agent(*, tenant_id: str, project_id: str, checkpointer, mutated: list, model_override: str | None = None, current_user: Any = None):
        # Deep agent: adds planning (write_todos), virtual files, summarization, skills,
        # and HITL on top of the Forge tools - so it can take a multi-step request,
        # build, verify with test_workflow, judge with evaluate_build, and keep
        # iterating until the result is actually correct.
        from deepagents import FilesystemPermission, create_deep_agent
        from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
        from langchain.agents.middleware import ModelFallbackMiddleware

        async with SessionLocal() as s:
            ctx = await build_compile_context(s, tenant_id=tenant_id, project_id=project_id, load_tools=False)
            proj = (await s.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
            ctx.project_config = (proj.config or {}) if proj else {}

        primary_ref = model_override or _assistant_model_ref(ctx)
        model = resolve_model(primary_ref, ctx, params={"thinking": True})
        middleware = []
        # If the strong model is unavailable at call time (bad ref, provider outage),
        # fall back to the project's default model instead of failing the assistant.
        fallback_ref = ctx.default_model
        if fallback_ref and fallback_ref != primary_ref and not str(fallback_ref).startswith("fake"):
            middleware.append(ModelFallbackMiddleware(resolve_model(fallback_ref, ctx)))

        # Optionally prune the (large) tool set per turn to cut tool-schema tokens.
        from alberto.config import settings as _settings
        if _settings.assistant_tool_selector:
            from langchain.agents.middleware import LLMToolSelectorMiddleware
            middleware.append(LLMToolSelectorMiddleware(model=model, max_tools=12))

        # Milestone 2.2: Contextual memory recall hook
        from alberto.nodes.agent_node import MemoryRecallMiddleware
        middleware.append(MemoryRecallMiddleware(tenant_id=tenant_id, project_id=project_id))

        tools = build_assistant_tools(tenant_id, project_id, mutated, current_user=current_user)
        kwargs: dict[str, Any] = {
            "model": model,
            "tools": tools,
            "system_prompt": SYSTEM_PROMPT,
            "middleware": middleware,
        }
        # The forge-platform skill (progressive disclosure: name+description at startup,
        # full guide read on demand) carries deep how-to knowledge without prompt bloat.
        if _SKILLS_DIR.exists():
            kwargs["backend"] = CompositeBackend(
                default=StateBackend(),
                routes={"/skills/": FilesystemBackend(root_dir=str(_SKILLS_DIR), virtual_mode=True)},
            )
            kwargs["skills"] = ["/skills/"]
            kwargs["permissions"] = [
                FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="deny"),
            ]
        # Destructive ops pause for human approval - REAL interrupts (needs checkpointer).
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer
            kwargs["interrupt_on"] = {"delete_workflow": True}
        return create_deep_agent(**kwargs)

    @staticmethod
    async def _persist_trace(
        *, tenant_id: str, project_id: str, thread_id: str | None, tracer,
        user_message: str = "", ai_response: str = "",
        token_metrics: dict | None = None,
        retrieval_meta: dict | None = None,
        error: str | None = None, status: str = "done",
        persona: str | None = None,
    ) -> None:
        """Persist one assistant turn as a Trace (name='assistant') + spans, so SPEND and
        the per-project reports include assistant usage like any workflow run. The turn is
        shown as a 'System' conversation in the Traces view (the Forge Assistant is internal)."""
        import uuid as _uuid
        from datetime import datetime

        from alberto.models import Span, Trace

        spans = tracer.ordered()
        if not spans:
            return
        tokens, cost = tracer.totals()
        started = min((s.start for s in spans), default=0.0)
        latency_ms = int((max((s.end or s.start for s in spans), default=started) - started) * 1000)
        trace_id = None
        try:
            async with SessionLocal() as s:
                trace_meta: dict[str, Any] = {}
                if token_metrics:
                    trace_meta["token_metrics"] = token_metrics
                if retrieval_meta:
                    trace_meta["retrieval"] = retrieval_meta
                from alberto.agents.router import AgentRouter
                spec = AgentRouter.resolve(persona, user_message)
                trace_name = spec.trace_name
                actor_name = spec.actor_name
                trace = Trace(
                    tenant_id=tenant_id, project_id=project_id, workflow_id=None,
                    run_id=f"assistant-{_uuid.uuid4()}", thread_id=thread_id,
                    name=trace_name, status=status,
                    started_at=datetime.utcnow(), ended_at=datetime.utcnow(),
                    latency_ms=latency_ms, total_tokens=tokens, total_cost_usd=cost,
                    source=trace_name,
                    actor=actor_name,
                    user_message=(user_message or None), ai_response=(ai_response or None),
                    error=(error or None),
                    meta=trace_meta,
                )
                s.add(trace)
                await s.flush()
                trace_id = trace.id
                for sr in spans:
                    s.add(Span(
                        id=sr.id, tenant_id=tenant_id, trace_id=trace.id,
                        parent_span_id=sr.parent_id, name=sr.name, kind=sr.kind,
                        latency_ms=sr.latency_ms, input=sr.input, output=sr.output, model=sr.model,
                        input_tokens=sr.input_tokens, output_tokens=sr.output_tokens,
                        cost_usd=sr.cost_usd, error=sr.error, attributes=sr.attributes,
                    ))
                await s.commit()

            # Schedule conversation learning asynchronously if turn completed successfully
            if status == "done" and user_message and ai_response and trace_id:
                try:
                    from alberto.services.learning_coordinator import LearningCoordinator
                    await LearningCoordinator.schedule_turn_learning(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_event_id=trace_id,
                        user_message=user_message,
                        ai_response=ai_response,
                    )
                except Exception as le:
                    log.warning("Failed to schedule assistant turn learning for trace %s: %s", trace_id, le)
        except Exception:  # noqa: BLE001 - tracing must never break the assistant
            pass

    @staticmethod
    async def _run(agent, payload, config, mutated: list) -> AsyncIterator[dict]:
        """Stream one agent turn: narration tokens, tool chips, todo updates, then either
        an interrupt frame (HITL approval needed) or done."""
        async for mode, chunk in agent.astream(payload, config, stream_mode=["messages", "updates"]):
            if mode == "messages":
                msg, _meta = chunk if isinstance(chunk, (list, tuple)) and len(chunk) == 2 else (chunk, {})
                # Only the agent's own narration - never echo tool-result or human messages.
                if getattr(msg, "type", "") not in ("ai", "AIMessageChunk"):
                    continue
                text = content_to_text(getattr(msg, "content", ""))
                if text:
                    # `id` segments the stream per AI message: the panel shows earlier
                    # segments as collapsible "thinking" and only the last as the answer.
                    yield {"event": "messages", "data": {"content": text, "id": getattr(msg, "id", None)}}
            elif mode == "updates" and isinstance(chunk, dict):
                for node_out in chunk.values():
                    if not isinstance(node_out, dict):
                        continue
                    # Plan visibility: surface write_todos state to the panel.
                    if node_out.get("todos") is not None:
                        yield {"event": "todos", "data": {"todos": jsonable(node_out["todos"])}}
                    for m in node_out.get("messages", []):
                        if getattr(m, "type", None) == "tool":
                            yield {"event": "tool", "data": {"name": getattr(m, "name", "tool"), "result": content_to_text(getattr(m, "content", ""))[:2000]}}

        snapshot = await agent.aget_state(config)
        interrupts = [
            jsonable(getattr(t, "interrupts", None))
            for t in getattr(snapshot, "tasks", [])
            if getattr(t, "interrupts", None)
        ]
        if interrupts:
            yield {"event": "interrupt", "data": {"interrupts": interrupts}}
        tracer_cb = next((cb for cb in config.get("callbacks", []) if hasattr(cb, "totals")), None)
        in_tok, out_tok, total_tok = tracer_cb.token_totals() if (tracer_cb and hasattr(tracer_cb, "token_totals")) else (0, 0, tracer_cb.totals()[0] if tracer_cb else 0)
        has_usage = tracer_cb.has_token_counts() if (tracer_cb and hasattr(tracer_cb, "has_token_counts")) else (total_tok > 0)
        yield {
            "event": "done",
            "data": {
                "mutated": mutated,
                "interrupted": bool(interrupts),
                "tokens": total_tok if has_usage else None,
                "prompt_tokens": in_tok if has_usage else None,
                "completion_tokens": out_tok if has_usage else None,
                "total_tokens": total_tok if has_usage else None,
            },
        }

    @staticmethod
    async def _fast_stream(
        *, tenant_id: str, project_id: str, messages: list[dict],
        thread_id: str | None = None, model: str | None = None,
        persona: str | None = None, current_user: Any = None,
    ) -> AsyncIterator[dict]:
        import time

        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from alberto.tracing.tracer import ForgeTracer

        tracer = ForgeTracer()
        async with SessionLocal() as s:
            ctx = await build_compile_context(s, tenant_id=tenant_id, project_id=project_id, load_tools=False)
            proj = (await s.execute(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))).scalar_one_or_none()
            ctx.project_config = (proj.config or {}) if proj else {}

            primary_ref = model or _assistant_model_ref(ctx)
            model_inst = resolve_model(primary_ref, ctx, params={"thinking": False})

            user_msg = next((m.get("content", "") for m in reversed(messages) if m.get("role") in ("user", "human")), "")

            # Decoupled Persona & Intent Routing via alberto.agents.router
            from alberto.agents.router import AgentRouter
            agent_spec = AgentRouter.resolve(persona, user_msg)
            mutated: list = []
            all_tools = build_assistant_tools(tenant_id, project_id, mutated, current_user=current_user)
            tools_to_bind = agent_spec.select_tools(all_tools, user_msg)
            runnable = model_inst.bind_tools(tools_to_bind) if tools_to_bind else model_inst

            live_context = await agent_spec.build_live_context(s, tenant_id, project_id)
            fast_sys_prompt = AgentRouter.get_system_prompt(agent_spec)
            if live_context:
                fast_sys_prompt = f"{fast_sys_prompt}{live_context}"

            # 1. Unified Knowledge & Memory Recall
            recalled_block = ""
            retrieval_meta: dict[str, Any] = {}
            if user_msg:
                try:
                    from alberto.services.context_assembler import ContextAssembler
                    from alberto.services.unified_memory import UnifiedMemoryManager

                    hits = await UnifiedMemoryManager.recall(
                        session=s,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        query=user_msg.strip(),
                        top_k=agent_spec.recall_top_k,
                    )
                    if hits:
                        recalled_block = ContextAssembler.assemble_context(hits)
                    retrieval_meta = {
                        "selected_sources": list(dict.fromkeys(h.source for h in hits)) if hits else [],
                        "matched_memory_ids": [h.record_id for h in hits],
                        "retrieved_context_items_count": len(hits),
                        "provenance": [h.provenance for h in hits if h.provenance],
                        "scores": [round(h.score, 3) for h in hits if h.score is not None],
                        "evidence_included": bool(recalled_block),
                    }
                except Exception as me:
                    log.warning("Assistant memory recall error: %s", me)

            if recalled_block:
                fast_sys_prompt = f"{fast_sys_prompt}\n\n{recalled_block}"

            # 2. Conversation History Retrieval & Context Window Budgeting
            history_turns: list[dict] = []
            if thread_id:
                from alberto.services.conversations import ConversationService

                try:
                    prior_traces = await ConversationService.turns(s, tenant_id, project_id, thread_id)
                    for pt in prior_traces:
                        if pt.user_message:
                            history_turns.append({"role": "user", "content": pt.user_message})
                        if pt.ai_response:
                            history_turns.append({"role": "assistant", "content": pt.ai_response})
                except Exception as he:
                    log.warning("Assistant history retrieval error: %s", he)

            if not history_turns and len(messages) > 1:
                # Explicit stateless messages sent by client
                history_turns = [m for m in messages if m.get("content")]
            elif user_msg:
                # Append current user prompt if not already present as the last turn
                if not (history_turns and history_turns[-1].get("role") == "user" and history_turns[-1].get("content") == user_msg):
                    history_turns.append({"role": "user", "content": user_msg})

            # Calculate context budget based on configured model context window
            ctx_max = 32768
            max_output = 4096
            try:
                reg = (ctx.registered_models or {}).get(primary_ref) or next(
                    (r for r in (ctx.registered_models or {}).values() if getattr(r, "model_name", None) == primary_ref),
                    None,
                )
                if reg:
                    ctx_max = getattr(reg, "context_window_configured", None) or getattr(reg, "context_window_max", None) or 32768
                    max_output = getattr(reg, "max_output_tokens", None) or 4096
            except Exception as re:
                log.warning("Failed to resolve model context budget from registry: %s", re)
            input_budget_chars = max(4000, (ctx_max - max_output) * 3)

            # Prioritize: (1) System prompt + (2) Current turn, then (3) Recent conversation turns
            if len(history_turns) > 1:
                current_turn_list = history_turns[-1:]
                older_turns = history_turns[:-1]
                base_chars = len(fast_sys_prompt) + len(current_turn_list[0].get("content", ""))
                available_chars = max(1000, input_budget_chars - base_chars)

                kept_older = []
                accum_chars = 0
                for m in reversed(older_turns):
                    c_len = len(m.get("content", ""))
                    if accum_chars + c_len > available_chars and kept_older:
                        break
                    kept_older.append(m)
                    accum_chars += c_len
                kept_older.reverse()
                final_turns = kept_older + current_turn_list
            else:
                final_turns = history_turns

            formatted_messages: list[Any] = [SystemMessage(content=fast_sys_prompt)]
            for m in final_turns:
                r = m.get("role", "user")
                c = m.get("content", "")
                if not c:
                    continue
                if r in ("user", "human"):
                    formatted_messages.append(HumanMessage(content=c))
                elif r in ("assistant", "ai"):
                    formatted_messages.append(AIMessage(content=c))

        config: Any = {"callbacks": [tracer]}
        final_text = ""
        err_msg: str | None = None
        t_start = time.monotonic()
        first_token_time: float | None = None
        last_token_time: float | None = None

        try:
            max_turns = 4
            turn = 0
            while turn < max_turns:
                turn += 1
                accum_content = ""
                accum_tool_calls: list[dict] = []
                async for chunk in runnable.astream(formatted_messages, config=config):
                    t_calls = getattr(chunk, "tool_calls", None) or []
                    for tc in t_calls:
                        if tc.get("name") and not any(x.get("id") == tc.get("id") or (x.get("name") == tc.get("name") and x.get("args") == tc.get("args")) for x in accum_tool_calls):
                            accum_tool_calls.append(tc)
                    txt = content_to_text(getattr(chunk, "content", ""))
                    if txt:
                        if first_token_time is None:
                            first_token_time = time.monotonic()
                        last_token_time = time.monotonic()
                        accum_content += txt
                        final_text += txt
                        yield {"event": "messages", "data": {"content": txt}}

                if not accum_tool_calls:
                    async for fb_frame in agent_spec.run_post_turn_fallback(
                        user_msg=user_msg,
                        tools_to_bind=tools_to_bind,
                        mutated=mutated,
                        final_text=final_text,
                    ):
                        if fb_frame.get("event") == "messages":
                            final_text += fb_frame.get("data", {}).get("content", "")
                        yield fb_frame
                    break

                # Ensure every tool call has a consistent unique ID
                for idx, tc in enumerate(accum_tool_calls):
                    if not tc.get("id"):
                        tc["id"] = f"call_{turn}_{idx}"

                formatted_messages.append(AIMessage(content=accum_content, tool_calls=accum_tool_calls))
                from langchain_core.messages import ToolMessage

                for tc in accum_tool_calls:
                    t_name = tc.get("name")
                    tc_id = tc["id"]
                    yield {"event": "tool", "data": {"name": t_name, "result": "running"}}
                    matched = next((t for t in tools_to_bind if t.name == t_name), None)
                    if matched:
                        try:
                            res = await asyncio.wait_for(matched.ainvoke(tc.get("args") or {}), timeout=90.0)
                            yield {"event": "tool", "data": {"name": t_name, "result": str(res)}}
                            formatted_messages.append(ToolMessage(tool_call_id=tc_id, content=_compact_tool_result(res)))
                        except Exception as te:
                            err_str = f"tool error: {te}"
                            yield {"event": "tool", "data": {"name": t_name, "result": err_str}}
                            formatted_messages.append(ToolMessage(tool_call_id=tc_id, content=_compact_tool_result(err_str)))
                    else:
                        err_str = f"Unknown tool: {t_name}"
                        yield {"event": "tool", "data": {"name": t_name, "result": err_str}}
                        formatted_messages.append(ToolMessage(tool_call_id=tc_id, content=_compact_tool_result(err_str)))

            in_tok, out_tok, total_tok = tracer.token_totals()
            has_usage = tracer.has_token_counts()
            yield {
                "event": "done",
                "data": {
                    "mutated": mutated,
                    "interrupted": False,
                    "tokens": total_tok if has_usage else None,
                    "prompt_tokens": in_tok if has_usage else None,
                    "completion_tokens": out_tok if has_usage else None,
                    "total_tokens": total_tok if has_usage else None,
                },
            }
        except Exception as e:
            err_msg = str(e)
            yield {"event": "error", "data": {"message": err_msg}}
        finally:
            ttft_s = (first_token_time - t_start) if first_token_time else None
            decode_s = (last_token_time - first_token_time) if (first_token_time and last_token_time) else None
            total_s = (time.monotonic() - t_start)
            in_tok, out_tok, total_tok = tracer.token_totals()
            has_usage = tracer.has_token_counts()
            tps = (out_tok / decode_s) if (has_usage and out_tok and decode_s and decode_s > 0.05) else None
            metrics = {
                "prompt_tokens": in_tok if has_usage else None,
                "completion_tokens": out_tok if has_usage else None,
                "total_tokens": total_tok if has_usage else None,
                "ttft_secs": round(ttft_s, 3) if ttft_s is not None else None,
                "decode_duration_secs": round(decode_s, 3) if decode_s is not None else None,
                "total_duration_secs": round(total_s, 3) if total_s is not None else None,
                "tokens_per_sec": round(tps, 1) if tps is not None else None,
            }
            await AssistantService._persist_trace(
                tenant_id=tenant_id, project_id=project_id, thread_id=thread_id, tracer=tracer,
                user_message=user_msg, ai_response=final_text,
                token_metrics=metrics,
                retrieval_meta=retrieval_meta,
                error=err_msg, status="error" if err_msg else "done",
                persona=persona,
            )

    @staticmethod
    async def stream(
        *, tenant_id: str, project_id: str, messages: list[dict],
        thread_id: str | None = None, checkpointer=None, model: str | None = None,
        thinking: bool = False, persona: str | None = None, current_user: Any = None,
    ) -> AsyncIterator[dict]:
        import time

        # Fast Butler Path: When thinking=False, skip heavy deep-agent loops & tool schemas
        if not thinking:
            async for frame in AssistantService._fast_stream(
                tenant_id=tenant_id, project_id=project_id, messages=messages,
                thread_id=thread_id, model=model, persona=persona, current_user=current_user,
            ):
                yield frame
            return

        mutated: list = []
        try:
            agent = await AssistantService._build_agent(
                tenant_id=tenant_id, project_id=project_id, checkpointer=checkpointer, mutated=mutated, model_override=model, current_user=current_user,
            )
        except Exception as e:  # noqa: BLE001
            yield {"event": "error", "data": {"message": f"assistant init failed: {e}"}}
            return

        lc_messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages if m.get("content")]
        # This turn's user text (for the Traces transcript).
        user_msg = next((m["content"] for m in reversed(lc_messages) if m.get("role", "user") in ("user", "human") and m.get("content")), "")
        final_text = ""
        from alberto.tracing.tracer import ForgeTracer

        tracer = ForgeTracer()
        # Generous recursion limit: the build→verify→judge→fix loop takes many steps.
        config: dict[str, Any] = {"recursion_limit": 100, "callbacks": [tracer]}
        if checkpointer is not None and thread_id:
            # Persistent conversation: the checkpointer holds history/todos/files for the
            # thread, so the frontend sends ONLY the new message.
            config["configurable"] = {"thread_id": f"assistant:{project_id}:{thread_id}"}
        t_start = time.monotonic()
        err_msg: str | None = None
        try:
            async for frame in AssistantService._run(agent, {"messages": lc_messages}, config, mutated):
                yield frame
            try:
                from alberto.services.runs import _last_ai_text

                snap = await agent.aget_state(config)
                final_text = _last_ai_text(getattr(snap, "values", {}) or {})
            except Exception:  # noqa: BLE001 - transcript capture must never break the turn
                pass
        except Exception as e:  # noqa: BLE001
            err_msg = str(e)
            yield {"event": "error", "data": {"message": str(e)}}
        finally:
            in_tok, out_tok, total_tok = tracer.token_totals()
            has_usage = tracer.has_token_counts()
            total_s = time.monotonic() - t_start
            metrics = {
                "prompt_tokens": in_tok if has_usage else None,
                "completion_tokens": out_tok if has_usage else None,
                "total_tokens": total_tok if has_usage else None,
                "total_duration_secs": round(total_s, 3),
            }
            await AssistantService._persist_trace(
                tenant_id=tenant_id, project_id=project_id, thread_id=thread_id, tracer=tracer,
                user_message=user_msg, ai_response=final_text,
                token_metrics=metrics,
                error=err_msg, status="error" if err_msg else "done",
                persona=persona,
            )

    @staticmethod
    async def resume(
        *, tenant_id: str, project_id: str, thread_id: str, decision: str = "approve",
        checkpointer=None, model: str | None = None,
        thinking: bool = False,
    ) -> AsyncIterator[dict]:
        """Resume after a HITL interrupt (e.g. delete_workflow approval)."""
        from langgraph.types import Command

        mutated: list = []
        if checkpointer is None or not thread_id:
            yield {"event": "error", "data": {"message": "resume requires a persistent assistant thread"}}
            return
        try:
            agent = await AssistantService._build_agent(
                tenant_id=tenant_id, project_id=project_id, checkpointer=checkpointer, mutated=mutated, model_override=model,
            )
        except Exception as e:  # noqa: BLE001
            yield {"event": "error", "data": {"message": f"assistant init failed: {e}"}}
            return
        from alberto.tracing.tracer import ForgeTracer

        tracer = ForgeTracer()
        config: dict[str, Any] = {
            "recursion_limit": 100,
            "configurable": {"thread_id": f"assistant:{project_id}:{thread_id}"},
            "callbacks": [tracer],
        }
        # HumanInTheLoopMiddleware resume shape: {"decisions": [{"type": "approve"|"reject"}]}.
        # If the paused turn had SEVERAL approval-gated tool calls, the middleware needs one
        # decision per call - expand the single UI decision to match (see _expand_hitl_decisions).
        from alberto.services.runs import _expand_hitl_decisions

        value: Any = {"decisions": [{"type": decision if decision in ("approve", "reject", "edit", "respond") else "approve"}]}
        value = await _expand_hitl_decisions(agent, config, value)
        try:
            async for frame in AssistantService._run(agent, Command(resume=value), config, mutated):
                yield frame
        except Exception as e:  # noqa: BLE001
            yield {"event": "error", "data": {"message": str(e)}}
        finally:
            await AssistantService._persist_trace(tenant_id=tenant_id, project_id=project_id, thread_id=thread_id, tracer=tracer)
