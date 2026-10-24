"""Flow-control nodes: start, end, router.

- `start` / `end` are passthrough markers; the compiler wires START -> entry_node
  and every `end` node -> END.
- `router` evaluates a sandboxed expression over state and routes to a case target.
  Its outgoing routing comes from `config.cases`/`config.default` (the compiler adds
  conditional edges), so labeled canvas edges out of a router are ignored at compile.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import time
from typing import Any
import jmespath

from langgraph.graph import END

from alberto.engine.context import CompileContext
from alberto.engine.expressions import ExpressionError, eval_expression, eval_truthy
from alberto.engine.registry import NodeSpec, Port, register

log = logging.getLogger("forge.flow")

# Keys a parallel_fanout stamps onto each child's Send payload (its INPUT state) so a child /
# a downstream join can reassemble results in a STABLE order despite the nondeterministic
# superstep completion order (audit F2). They ride only in the Send payload (verified: extra
# Send-payload keys reach the child but never enter global workflow state), so they need not be
# declared in `state` and never leak to the run output.
FANOUT_INDEX_KEY = "_fanout_index"
FANOUT_TOTAL_KEY = "_fanout_total"


def _passthrough(state: dict) -> dict:
    return {}


def start_factory(config: dict, ctx: CompileContext):
    return _passthrough


def end_factory(config: dict, ctx: CompileContext):
    return _passthrough


def make_router_path(config: dict):
    """Build a LangGraph path function: state -> target node id (or END).

    Supports both low-code Switch `rules` (equals/contains/gt/lt/exists) and
    advanced sandboxed `expression` evaluations.
    """
    expr = config.get("expression")
    cases = config.get("cases", {}) or {}
    rules = config.get("rules") or []
    default = config.get("default")
    multi = bool(config.get("multi", False))

    def _eval_rule(rule: dict, state: dict) -> bool:
        op = rule.get("op") or rule.get("operator", "equals")
        prop = (rule.get("property") or "").replace("msg.", "")
        expected = rule.get("value")
        actual = state.get(prop)
        if actual is None and prop:
            try:
                actual = jmespath.search(prop, state)
            except Exception:
                actual = None
        if actual is None and "msg" in state and isinstance(state["msg"], dict) and prop:
            try:
                actual = jmespath.search(prop, state["msg"])
            except Exception:
                actual = None

        if op in ("eq", "equals", "=="):
            if isinstance(expected, bool):
                return str(actual).lower() == str(expected).lower()
            return actual == expected or str(actual) == str(expected)
        if op in ("neq", "not_equals", "!="):
            return actual != expected and str(actual) != str(expected)
        if op in ("contains",):
            return str(expected).lower() in str(actual).lower() if actual is not None else False
        if op in ("gt", "greater_than", ">"):
            if actual is None or expected is None:
                return False
            try:
                return float(actual) > float(expected)
            except Exception:
                return False
        if op in ("lt", "less_than", "<"):
            if actual is None or expected is None:
                return False
            try:
                return float(actual) < float(expected)
            except Exception:
                return False
        if op in ("exists",):
            return actual is not None
        if op in ("empty", "is_empty"):
            if actual is None:
                return False
            if hasattr(actual, "__len__"):
                return len(actual) == 0
            return not actual
        if op in ("true", "is_true"):
            return bool(actual) is True
        if op in ("false", "is_false"):
            return bool(actual) is False
        return False

    def _one(val: Any) -> str | None:
        target = cases.get(str(val))
        if target is None and isinstance(val, bool):
            target = cases.get(str(val).lower())
        if target is None and not isinstance(val, str) and val in cases:
            target = cases[val]
        return target

    def _path(state: dict) -> Any:
        state_dict = dict(state or {})
        if rules:
            matched: list[str] = []
            for r in rules:
                if _eval_rule(r, state_dict):
                    tgt = r.get("target")
                    if tgt:
                        if multi:
                            if tgt not in matched:
                                matched.append(tgt)
                        else:
                            return tgt
            if matched:
                return matched
            return default if default else END

        if not expr:
            return default if default else END

        try:
            val = eval_expression(expr, state_dict)
        except ExpressionError as e:
            # A failing router expression silently ending the run is a debugging nightmare;
            # log it (and fall through to the default/END) so it's traceable (audit F10).
            log.warning("router expression %r failed: %s", expr, e)
            val = None
        if multi:
            vals = list(val) if isinstance(val, (list, tuple, set)) else ([val] if val is not None else [])
            targets: list[str] = []
            for v in vals:
                t = _one(v)
                if t and t not in targets:
                    targets.append(t)
            if targets:
                return targets
            if not default:
                log.warning("router %r matched no case and has no default; ending the run", expr)
            return default if default else END
        target = _one(val)
        if target is None:
            if not default:
                log.warning("router %r value %r matched no case and has no default; ending the run", expr, val)
            target = default
        return target if target else END

    return _path


def router_factory(config: dict, ctx: CompileContext):
    # The node itself is a passthrough; routing is added as conditional edges.
    return _passthrough


def subworkflow_factory(config: dict, ctx: CompileContext):
    """Compile a referenced workflow as a nested graph node (reusable component).

    The sub-graph shares the parent's tool/agent/auth context but carries NO checkpointer
    (the top-level workflow owns durability - same rule as embedded agents). Recursion is
    broken by tracking in-progress workflow ids on the context.

    Key mapping (audit F6): by default parent and child share state keys by name (the child
    reads/writes the same `messages` etc.). When `input_mapping` / `output_mapping` are set the
    node instead runs the child in ISOLATION and copies only the mapped keys across:
      - input_mapping:  {parent_state_key: child_state_key}  (parent -> child, before the run)
      - output_mapping: {child_state_key: parent_state_key}  (child -> parent, after the run)
    `version`, when given, is honored best-effort: only the project's CURRENT executable per
    workflow id is available here, so a mismatch is logged rather than silently ignored."""
    import dataclasses

    from alberto.engine.compiler import compile_workflow

    ref = config["workflow_id"]
    sub_def = (getattr(ctx, "workflows", {}) or {}).get(ref)
    if not sub_def:
        def _missing(state: dict) -> dict:
            return {}
        return _missing

    want_version = config.get("version")
    if want_version is not None and sub_def.get("version") != want_version:
        # The runtime only carries the latest executable per workflow id/name (see
        # runtime.make_runtime_ctx), so we can't pin an older version here - surface it
        # instead of pretending the request was honored. Full pinning needs a
        # version-keyed workflow store (noted for a follow-up).
        log.warning(
            "subworkflow %r requested version %s but only version %s is available; using it",
            ref, want_version, sub_def.get("version"),
        )

    compiling = getattr(ctx, "compiling", set())
    if ref in compiling:  # cycle: refuse to recurse
        def _cycle(state: dict) -> dict:
            return {}
        return _cycle

    compiling.add(ref)
    try:
        sub_ctx = dataclasses.replace(ctx, checkpointer=None, store=None)
        sub_graph = compile_workflow(sub_def, sub_ctx)
    finally:
        compiling.discard(ref)

    input_mapping = config.get("input_mapping") or {}
    output_mapping = config.get("output_mapping") or {}
    if not input_mapping and not output_mapping:
        # Shared-state fast path (unchanged behavior): LangGraph runs the compiled child as a
        # subgraph, sharing state keys by name and bubbling interrupts up for HITL.
        return sub_graph

    from alberto.nodes.data import _set_nested

    def _extract_val(k: str, container: dict) -> Any:
        if not isinstance(container, dict):
            return None
        v = container.get(k)
        if v is not None:
            return v
        try:
            res = jmespath.search(k, container)
            if res is not None:
                return res
        except Exception:
            pass
        if k.startswith("msg."):
            try:
                res = jmespath.search(k[4:], container)
                if res is not None:
                    return res
            except Exception:
                pass
        return None

    async def _mapped(state: dict, config=None) -> dict:
        child_in: dict[str, Any] = {}
        for k1, k2 in input_mapping.items():
            # Support both {child_param: parent_src} and {parent_src: child_param}
            val = _extract_val(k2, state)
            if val is not None:
                child_in[k1] = val
            else:
                val = _extract_val(k1, state)
                if val is not None:
                    child_in[k2] = val

        child_out = await sub_graph.ainvoke(child_in, config)
        out: dict[str, Any] = {}
        for k1, k2 in output_mapping.items():
            # Support both {child_src: parent_target} and {parent_target: child_src}
            val = _extract_val(k1, child_out)
            target = k2
            if val is None:
                val = _extract_val(k2, child_out)
                target = k1
            if val is not None:
                if "." in target:
                    _set_nested(out, target, val)
                else:
                    out[target] = val
        return out

    return _mapped


def loop_factory(config: dict, ctx: CompileContext):
    """Iterate: increment `_loop_count` and write `_loop` = 'continue'/'done' so a router
    can loop the body back here. Stops at `max_iter` or when `condition` is falsy. The
    body edge must return to this node (it `allows_cycle`); declare `_loop_count`/`_loop`
    in state (the canvas auto-declares node-written keys)."""
    max_iter = int(config.get("max_iter", 10))
    condition = config.get("condition")

    def _node(state: dict) -> dict:
        # `_loop_count` is the running firing count; stop once it reaches max_iter. (Counting
        # contract is intentionally stable - see test_loop_node_counts_and_stops.)
        i = int(state.get("_loop_count", 0)) + 1
        cont = i < max_iter
        if cont and condition:
            try:
                cont = eval_truthy(condition, dict(state))
            except ExpressionError as e:
                # A failing loop condition silently ending the loop is hard to debug; log it.
                log.warning("loop condition %r failed: %s", condition, e)
                cont = False
        return {"_loop_count": i, "_loop": "continue" if cont else "done"}

    return _node


def make_fanout_path(config: dict):
    """LangGraph Send-based map: run `child_node` once per item in `state[over]`, with the
    item placed at `item_key`. Children aggregate via an `add`-reducer state key.

    Each Send payload is also stamped with the item's 0-based input index (`index_key`,
    default `_fanout_index`) and the batch size (`_fanout_total`) so a child - or a
    downstream join - can restore a STABLE order over the nondeterministic superstep
    completion order (audit F2). These extra keys live only in the child's input state and
    never enter the shared workflow state, so they need no `state` declaration."""
    from langgraph.types import Send

    over = config["over"]
    child = config.get("child_node") or config.get("target")
    item_key = config.get("item_key") or "payload"
    index_key = config.get("index_key") or FANOUT_INDEX_KEY

    def _path(state: dict) -> Any:
        items = state.get(over)
        if items is None and over:
            try:
                items = jmespath.search(over, state)
            except Exception:
                items = None
            if items is None and over.startswith("msg."):
                try:
                    items = jmespath.search(over[4:], state)
                except Exception:
                    items = None
        if not items:
            items = []
            # An empty fan-out produces no Sends, so the child (and anything gated on its
            # aggregated output) never runs. Log it so an empty `over` isn't a silent
            # dead-end the operator can't see (audit F10).
            log.warning("parallel_fanout over %r produced no items; no children dispatched", over)
        total = len(items)
        return [
            Send(child, {item_key: item, index_key: i, FANOUT_TOTAL_KEY: total})
            for i, item in enumerate(items)
        ]

    return _path


def resilient_fanout_child(fn, *, timeout: float | None = None, isolate: bool = False):
    """Wrap a parallel_fanout child so one item's failure/timeout doesn't abort the whole
    superstep (partial-failure isolation) and a slow item can be bounded (per-item timeout).

    Only applied when the workflow opts in (error_policy "continue" or the fanout's
    on_item_error="skip"/item_timeout_seconds) - the compiler decides. LangGraph control-flow
    signals (interrupts / Command bubbling, `GraphBubbleUp`) and cancellation are ALWAYS
    re-raised so HITL keeps working; only genuine errors are isolated. A skipped item
    contributes no state update ({}). Sync children run inline and can't be preempted, so the
    per-item timeout applies to async children / compiled subgraphs only."""
    import asyncio
    import inspect

    from langgraph.errors import GraphBubbleUp

    is_runnable = hasattr(fn, "ainvoke")
    is_coro = inspect.iscoroutinefunction(fn)
    accepts_config = False
    if not is_runnable:
        try:
            accepts_config = len(inspect.signature(fn).parameters) >= 2
        except (TypeError, ValueError):
            accepts_config = False

    async def _invoke(state: dict, config):
        if is_runnable:
            return await fn.ainvoke(state, config)
        if is_coro:
            return await (fn(state, config) if accepts_config else fn(state))
        # Plain sync node: call inline (JMESPath transforms etc. are trivial). It runs on the
        # event loop, so it can't be timed out - documented above.
        return fn(state, config) if accepts_config else fn(state)

    async def _wrapped(state: dict, config=None) -> dict:
        idx = state.get(FANOUT_INDEX_KEY)
        try:
            if timeout and (is_runnable or is_coro):
                return await asyncio.wait_for(_invoke(state, config), timeout)
            return await _invoke(state, config)
        except GraphBubbleUp:
            raise  # interrupts / Command bubbling must reach the parent for HITL to work
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - isolate a single item's failure when opted in
            if not isolate:
                raise
            log.warning(
                "parallel_fanout child failed for item #%s (%s: %s); skipping it",
                idx, type(e).__name__, e,
            )
            return {}

    return _wrapped


def _apply_join_reducer(reducer: str, value: Any) -> Any:
    """Aggregate a fan-in value per the join `reducer`. `value` is the list the fan-out
    children accumulated into a state key (via that key's `add` reducer)."""
    if not isinstance(value, list):
        # A lone/non-list value has nothing to aggregate: concat/first/last are identity, and
        # merge on a single dict is identity too.
        return value
    if reducer == "first":
        return value[0] if value else None
    if reducer == "last":
        return value[-1] if value else None
    if reducer == "merge":
        merged: dict[str, Any] = {}
        for v in value:
            if isinstance(v, dict):
                merged.update(v)
        return merged
    # concat (default): flatten one level when children each contributed a list, else the
    # already-flat accumulated list is the concatenation.
    if value and all(isinstance(v, list) for v in value):
        return [x for sub in value for x in sub]
    return value


def join_factory(config: dict, ctx: CompileContext):
    """Converge parallel branches.

    Supports explicit reducers across incoming branches:
    - 'branch_map': maps {node_id: branch_payload} for each incoming branch
    - 'array' / 'list': collects all branch payloads into a deterministically ordered list
    - 'merge': merges branch dictionaries without silent loss
    - 'concat': concatenates list outputs or aggregates input_key
    """
    reducer = config.get("reducer", "merge")
    input_key = config.get("input_key")
    output_key = config.get("output_key") or input_key or "payload"

    def _node(state: dict) -> dict:
        branches = state.get("_branches") or (
            state.get("msg", {}).get("_branches") if isinstance(state.get("msg"), dict) else {}
        )
        incoming = config.get("incoming_nodes") or []
        if incoming and isinstance(branches, dict):
            branches = {k: v for k, v in branches.items() if k in incoming}
        if reducer == "branch_map" and branches:
            res = {output_key: branches}
            if output_key == "payload":
                cur_msg = dict(state.get("msg") or {})
                cur_msg["payload"] = branches
                res["msg"] = cur_msg
            return res
        if reducer in ("array", "list") and branches:
            arr = [branches[k] for k in sorted(branches.keys())]
            res = {output_key: arr}
            if output_key == "payload":
                cur_msg = dict(state.get("msg") or {})
                cur_msg["payload"] = arr
                res["msg"] = cur_msg
            return res
        if reducer == "merge" and branches:
            import copy

            def _merge_values(a: Any, b: Any) -> Any:
                if a == b:
                    return copy.deepcopy(a)
                if isinstance(a, dict) and isinstance(b, dict):
                    res = dict(a)
                    for k, v in b.items():
                        if k in res:
                            res[k] = _merge_values(res[k], v)
                        else:
                            res[k] = copy.deepcopy(v)
                    return res
                if isinstance(a, list) and isinstance(b, list):
                    return copy.deepcopy(a) + copy.deepcopy(b)
                if isinstance(a, list):
                    res = copy.deepcopy(a)
                    if b not in res:
                        res.append(copy.deepcopy(b))
                    return res
                if isinstance(b, list):
                    res = copy.deepcopy(b)
                    if a not in res:
                        res.insert(0, copy.deepcopy(a))
                    return res
                return [a, b]

            all_scalars = all(not isinstance(branches[k], dict) for k in branches)
            if all_scalars:
                merged_val = [branches[k] for k in sorted(branches.keys())]
            else:
                merged = {}
                for b_id in sorted(branches.keys()):
                    b_val = branches[b_id]
                    if isinstance(b_val, dict):
                        for k, v in b_val.items():
                            if k not in merged:
                                merged[k] = copy.deepcopy(v)
                            else:
                                merged[k] = _merge_values(merged[k], v)
                    else:
                        merged[b_id] = b_val
                merged_val = merged

            res = {output_key: merged_val}
            if output_key == "payload":
                cur_msg = dict(state.get("msg") or {})
                cur_msg["payload"] = merged_val
                res["msg"] = cur_msg
            return res
        if input_key:
            val = _apply_join_reducer(reducer, state.get(input_key))
            res = {output_key: val}
            if output_key == "payload":
                cur_msg = dict(state.get("msg") or {})
                cur_msg["payload"] = val
                res["msg"] = cur_msg
            return res
        return {}

    return _node


def router_targets(config: dict) -> list[str]:
    cases = config.get("cases", {}) or {}
    targets = list(cases.values())
    for r in (config.get("rules") or []):
        if r.get("target"):
            targets.append(r["target"])
    if config.get("default"):
        targets.append(config["default"])
    return sorted(set(targets))


def inject_factory(config: dict, ctx: CompileContext):
    payload_raw = config.get("payload")
    payload_type = config.get("payload_type", "json")
    topic = config.get("topic", "")
    output_key = config.get("output_key", "payload")

    def _node(state: dict) -> dict:
        now = time.time()
        payload = payload_raw
        if payload_raw is None and state.get(output_key) is not None:
            payload = state.get(output_key)
        elif payload_type in ("timestamp", "date"):
            payload = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc).isoformat()
        elif payload_type == "number":
            try:
                payload = float(payload_raw) if "." in str(payload_raw) else int(payload_raw)
            except Exception:
                payload = 0
        elif payload_type == "boolean":
            payload = str(payload_raw).lower() in ("true", "1", "yes")
        elif payload_type == "string":
            payload = str(payload_raw) if payload_raw is not None else ""
        elif payload_type == "json" and isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = payload_raw

        msg = {
            "payload": payload,
            "topic": topic,
            "metadata": {"timestamp": now, "source": "inject"},
        }
        return {
            output_key: payload,
            "msg": msg,
            "topic": topic,
            "payload": payload,
        }

    return _node


def debug_factory(config: dict, ctx: CompileContext):
    target = config.get("target", "payload")
    active = config.get("active", True)
    complete = config.get("complete", False)
    node_id = config.get("id", "debug")

    def _node(state: dict) -> dict:
        if not active:
            return {}
        try:
            from langgraph.config import get_stream_writer
            from alberto.services.tool_policy import ToolPolicyService

            state_dict = dict(state or {})
            if complete or target in ("complete msg", "msg"):
                val = state_dict.get("msg") or state_dict
            elif target in state_dict:
                val = state_dict[target]
            else:
                try:
                    val = jmespath.search(target, state_dict)
                except Exception:
                    val = state_dict.get("payload", state_dict)

            scrubbed = ToolPolicyService._scrub_sensitive_dict(val)
            writer = get_stream_writer()
            writer({
                "channel": "debug",
                "payload": {
                    "node_id": node_id,
                    "target": target,
                    "data": scrubbed,
                    "timestamp": time.time(),
                },
            })
        except Exception:
            pass
        return {}

    return _node


def delay_factory(config: dict, ctx: CompileContext):
    seconds = float(config.get("seconds", 1))
    unit = config.get("unit", "seconds")
    multiplier = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}.get(unit, 1)
    duration = seconds * multiplier
    mode = config.get("mode") or ("durable" if config.get("durable") else "in_memory")

    async def _node(state: dict) -> dict:
        if mode == "durable":
            from langgraph.types import interrupt
            now = datetime.datetime.now(datetime.timezone.utc)
            deadline = now + datetime.timedelta(seconds=duration)
            interrupt({
                "type": "delay",
                "duration": duration,
                "deadline": deadline.isoformat(),
                "node_id": config.get("id", "delay"),
            })
            return {}
        else:
            if duration > 0:
                await asyncio.sleep(min(duration, 60.0))
            return {}

    return _node


register(
    NodeSpec(
        type="start",
        schema_id="forge/nodes/start",
        input_ports=[],
        output_ports=[Port(id="out", io_type="control", direction="out")],
        factory=start_factory,
        category="flow",
        label="Start",
        description="Entry marker",
        summarize=lambda c: [],
    )
)

register(
    NodeSpec(
        type="end",
        schema_id="forge/nodes/end",
        input_ports=[Port(id="in", io_type="control", direction="in")],
        output_ports=[],
        factory=end_factory,
        category="flow",
        label="End",
        description="Terminal node",
        summarize=lambda c: [],
    )
)

register(
    NodeSpec(
        type="loop",
        schema_id="forge/nodes/loop",
        input_ports=[Port(id="in", io_type="any", direction="in")],
        output_ports=[Port(id="out", io_type="any", direction="out")],
        factory=loop_factory,
        allows_cycle=True,
        category="flow",
        label="Loop",
        description="Iterate the body until a condition/max-iterations (writes _loop=continue/done).",
        summarize=lambda c: [f"max {c.get('max_iter', 10)}", c.get("condition", "")[:32]],
    )
)

register(
    NodeSpec(
        type="parallel_fanout",
        schema_id="forge/nodes/parallel_fanout",
        input_ports=[Port(id="in", io_type="json", direction="in")],
        output_ports=[Port(id="out", io_type="control", direction="out", many=True)],
        factory=lambda c, ctx: _passthrough,
        category="flow",
        label="Parallel Fanout",
        description="Map a list: run a child node per item in parallel (Send).",
        summarize=lambda c: [f"over {c.get('over', '-')} → {c.get('child_node', '-')}"],
    )
)

register(
    NodeSpec(
        type="join",
        schema_id="forge/nodes/join",
        input_ports=[Port(id="in", io_type="control", direction="in", many=True)],
        output_ports=[Port(id="out", io_type="json", direction="out")],
        factory=join_factory,
        category="flow",
        label="Join",
        description="Converge parallel branches; optionally re-aggregate a key via the reducer.",
        summarize=lambda c: [
            f"reducer · {c.get('reducer', 'concat')}"
            + (f" · {c.get('input_key')}→{c.get('output_key') or c.get('input_key')}" if c.get("input_key") else "")
        ],
    )
)

register(
    NodeSpec(
        type="subworkflow",
        schema_id="forge/nodes/subworkflow",
        input_ports=[Port(id="in", io_type="any", direction="in")],
        output_ports=[Port(id="out", io_type="any", direction="out")],
        factory=subworkflow_factory,
        category="flow",
        label="Subworkflow",
        description="Run another workflow as a reusable component.",
        summarize=lambda c: [f"→ {c.get('workflow_id', '-')}"],
    )
)

register(
    NodeSpec(
        type="router",
        schema_id="forge/nodes/router",
        input_ports=[Port(id="in", io_type="any", direction="in")],
        output_ports=[Port(id="out", io_type="control", direction="out", many=True)],
        factory=router_factory,
        category="flow",
        label="Router",
        description="Conditional branch",
        summarize=lambda c: [
            f"expression · {c.get('expression', '')}" + (" · multi" if c.get("multi") else ""),
            " · ".join(list((c.get('cases') or {}).keys()) + (["default"] if c.get("default") else [])),
        ],
    )
)

register(
    NodeSpec(
        type="switch",
        schema_id="forge/nodes/router",
        input_ports=[Port(id="in", io_type="any", direction="in")],
        output_ports=[Port(id="out", io_type="control", direction="out", many=True)],
        factory=router_factory,
        category="flow",
        label="Switch",
        description="Node-RED visual rule switch and router",
        summarize=lambda c: [
            f"rules · {len(c.get('rules', []))}",
        ],
    )
)

register(
    NodeSpec(
        type="passthrough",
        schema_id="forge/nodes/start",
        input_ports=[Port(id="in", io_type="any", direction="in")],
        output_ports=[Port(id="out", io_type="any", direction="out")],
        factory=lambda c, ctx: _passthrough,
        category="flow",
        label="Passthrough",
        description="Identity passthrough node",
        summarize=lambda c: [],
    )
)

register(
    NodeSpec(
        type="inject",
        schema_id="forge/nodes/inject",
        input_ports=[],
        output_ports=[Port(id="out", io_type="any", direction="out")],
        factory=inject_factory,
        category="flow",
        label="Inject",
        description="Manual trigger & test message generator.",
        summarize=lambda c: [f"{c.get('payload_type', 'json')} · {str(c.get('payload', ''))[:20]}"],
    )
)

register(
    NodeSpec(
        type="debug",
        schema_id="forge/nodes/debug",
        input_ports=[Port(id="in", io_type="any", direction="in")],
        output_ports=[Port(id="out", io_type="any", direction="out")],
        factory=debug_factory,
        category="flow",
        label="Debug",
        description="Inspect message payload & debug stream.",
        summarize=lambda c: [f"inspect · {c.get('target', 'payload')}" + (" (disabled)" if c.get("active") is False else "")],
    )
)

register(
    NodeSpec(
        type="delay",
        schema_id="forge/nodes/delay",
        input_ports=[Port(id="in", io_type="any", direction="in")],
        output_ports=[Port(id="out", io_type="any", direction="out")],
        factory=delay_factory,
        category="flow",
        label="Delay",
        description="Wait for a specified duration.",
        summarize=lambda c: [f"wait {c.get('seconds', 1)} {c.get('unit', 's')}"],
    )
)
