"""Build a runtime state schema (TypedDict) from a workflow's declared state.

Doc 2 §6 / Doc 4 §2: state is a `TypedDict` (NOT pydantic, hard v1 constraint).
Each field maps to a python type + a reducer so parallel writes merge correctly.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import add_messages

# Doc 4 StateFieldSpec.type -> python type used for the channel.
PY_TYPES: dict[str, Any] = {
    "list[message]": list,
    "list[str]": list,
    "list[json]": list,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "json": dict,
}


def _merge(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


def _merge_payload(a: Any, b: Any) -> Any:
    if a is None:
        return b
    if b is None:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        base = dict(a)
        for k, v in b.items():
            if isinstance(base.get(k), dict) and isinstance(v, dict):
                base[k] = _merge_payload(base[k], v)
            else:
                base[k] = v
        return base
    return b


def _last_value(a: Any, b: Any) -> Any:
    return b if b is not None else a


def _merge_msg(a: dict | None, b: dict | None) -> dict:
    if not a:
        return dict(b or {})
    if not b:
        return dict(a or {})
    res = {**a, **b}
    res["payload"] = _merge_payload(a.get("payload"), b.get("payload"))
    if isinstance(a.get("metadata"), dict) and isinstance(b.get("metadata"), dict):
        res["metadata"] = {**a["metadata"], **b["metadata"]}
    if "_branches" in a or "_branches" in b:
        res["_branches"] = {**(a.get("_branches") or {}), **(b.get("_branches") or {})}
    if a.get("topic") and b.get("topic") and a["topic"] != b["topic"]:
        res["topic"] = ",".join(sorted({a["topic"], b["topic"]}))
    return res


# Doc 4 StateFieldSpec.reducer -> binary reducer. "last" => no reducer (LastValue/overwrite).
REDUCERS: dict[str, Any] = {
    "add_messages": add_messages,
    "add": operator.add,
    "merge": _merge,
    "merge_msg": _merge_msg,
    "merge_payload": _merge_payload,
    "last_value": _last_value,
    # "last" intentionally absent: a plain annotation => overwrite semantics.
}

# Sensible default so agent nodes always have a messages channel to read/write.
_DEFAULT_MESSAGES = {"type": "list[message]", "reducer": "add_messages"}


def build_state_typeddict(state_cfg: dict[str, dict], name: str = "WorkflowState") -> type:
    """Compile a state-schema dict into a `TypedDict` with reducer annotations.

    Example input (executable JSON `state`):
        {"messages": {"type": "list[message]", "reducer": "add_messages"},
         "findings": {"type": "list[str]",     "reducer": "add"},
         "intent":   {"type": "str",           "reducer": "last"}}
    """
    cfg = dict(state_cfg or {})
    cfg.setdefault("messages", _DEFAULT_MESSAGES)
    cfg.setdefault("msg", {"type": "json", "reducer": "merge_msg"})
    cfg.setdefault("payload", {"type": "json", "reducer": "merge_payload"})
    cfg.setdefault("topic", {"type": "str", "reducer": "last_value"})
    cfg.setdefault("_branches", {"type": "json", "reducer": "merge"})

    annotations: dict[str, Any] = {}
    for field, spec in cfg.items():
        py = PY_TYPES.get(spec.get("type", "json"), Any)
        reducer_name = spec.get("reducer", "last")
        reducer = REDUCERS.get(reducer_name)
        annotations[field] = Annotated[py, reducer] if reducer is not None else py

    # Functional TypedDict carries Annotated reducer metadata that LangGraph reads
    # when building channels. total=False: nodes may write a partial state update.
    return TypedDict(name, annotations, total=False)  # type: ignore[operator]
