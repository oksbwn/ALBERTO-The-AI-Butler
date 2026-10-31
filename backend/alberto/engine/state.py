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


def _merge_concurrent_payload(a: Any, b: Any) -> Any:
    if a is None:
        return b
    if b is None:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        res = dict(a)
        for k, v in b.items():
            if k not in res:
                res[k] = v
            elif isinstance(res[k], dict) and isinstance(v, dict):
                res[k] = _merge_concurrent_payload(res[k], v)
            else:
                res[k] = v
        return res
    return b


def _delete_nested_path(d: dict, path: str) -> None:
    if not path or not isinstance(d, dict):
        return
    parts = [p for p in path.split(".") if p]
    curr = d
    for p in parts[:-1]:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            return
    if isinstance(curr, dict) and parts:
        curr.pop(parts[-1], None)


def _clean_special_keys(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("_deleted_keys", "_replace_payload", "_full_replacement")}


def _merge_payload(a: Any, b: Any) -> Any:
    if b is None:
        if isinstance(a, dict):
            return _clean_special_keys(a)
        return a
    if a is None:
        if isinstance(b, dict):
            return _clean_special_keys(b)
        return b
    if isinstance(b, dict) and (b.get("_replace_payload") or b.get("_full_replacement")):
        # Full payload replacement: discard prior keys without requiring explicit delete markers
        return _clean_special_keys(b)
    if isinstance(a, dict) and isinstance(b, dict):
        res = _clean_special_keys(a)
        res.update(_clean_special_keys(b))
        for d in b.get("_deleted_keys", []):
            prop = str(d)
            if prop.startswith("msg."):
                prop = prop[4:]
            if prop.startswith("payload."):
                prop = prop[8:]
            _delete_nested_path(res, prop)
        return res
    return b


def _last_value(a: Any, b: Any) -> Any:
    return b if b is not None else a


def _merge_msg(a: dict | None, b: dict | None) -> dict:
    if not a:
        res_b = dict(b or {})
        res_b.pop("_deleted_keys", None)
        if isinstance(res_b.get("payload"), dict):
            res_b["payload"] = {k: v for k, v in res_b["payload"].items() if k != "_deleted_keys"}
        return res_b
    if not b:
        res_a = dict(a or {})
        res_a.pop("_deleted_keys", None)
        if isinstance(res_a.get("payload"), dict):
            res_a["payload"] = {k: v for k, v in res_a["payload"].items() if k != "_deleted_keys"}
        return res_a

    branches = {}
    if isinstance(a.get("_branches"), dict):
        branches.update(a["_branches"])
    if isinstance(b.get("_branches"), dict):
        branches.update(b["_branches"])

    meta = {}
    if isinstance(a.get("metadata"), dict):
        meta.update(a["metadata"])
    if isinstance(b.get("metadata"), dict):
        meta.update(b["metadata"])

    res = {k: v for k, v in a.items() if k != "_deleted_keys"}
    res.update({k: v for k, v in b.items() if k != "_deleted_keys"})
    if "payload" in a and "payload" in b:
        res["payload"] = _merge_payload(a["payload"], b["payload"])
    elif "payload" in b:
        res["payload"] = _merge_payload(None, b["payload"])
    elif "payload" in a:
        res["payload"] = _merge_payload(a["payload"], None)

    for d in b.get("_deleted_keys", []):
        prop = str(d)
        if prop.startswith("msg."):
            prop = prop[4:]
        if prop.startswith("payload."):
            prop = prop[8:]
        if isinstance(res.get("payload"), dict):
            _delete_nested_path(res["payload"], prop)

    if branches:
        res["_branches"] = branches
    if meta:
        res["metadata"] = meta
    if a.get("topic") and b.get("topic") and a["topic"] != b["topic"]:
        res["topic"] = ",".join(sorted({str(a["topic"]), str(b["topic"])}))
    return res


# Doc 4 StateFieldSpec.reducer -> binary reducer. "last" => no reducer (LastValue/overwrite).
def _merge_branch_turns(a: dict | None, b: dict | None) -> dict:
    if not a:
        return dict(b or {})
    if not b:
        return dict(a or {})
    res = {k: list(v) if isinstance(v, list) else [v] for k, v in a.items()}
    for k, v in b.items():
        v_list = list(v) if isinstance(v, list) else [v]
        if k in res:
            res[k].extend(v_list)
        else:
            res[k] = list(v_list)
    return res

REDUCERS: dict[str, Any] = {
    "add_messages": add_messages,
    "add": operator.add,
    "merge": _merge,
    "merge_msg": _merge_msg,
    "merge_payload": _merge_payload,
    "merge_branch_turns": _merge_branch_turns,
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
    cfg.setdefault("output", {"type": "json", "reducer": "last_value"})
    cfg.setdefault("tool_result", {"type": "json", "reducer": "last_value"})
    cfg.setdefault("topic", {"type": "str", "reducer": "last_value"})
    cfg.setdefault("_branches", {"type": "json", "reducer": "merge"})
    cfg.setdefault("_branch_turns", {"type": "json", "reducer": "merge_branch_turns"})

    annotations: dict[str, Any] = {}
    for field, spec in cfg.items():
        py = PY_TYPES.get(spec.get("type", "json"), Any)
        reducer_name = spec.get("reducer", "last")
        reducer = REDUCERS.get(reducer_name)
        annotations[field] = Annotated[py, reducer] if reducer is not None else py

    # Functional TypedDict carries Annotated reducer metadata that LangGraph reads
    # when building channels. total=False: nodes may write a partial state update.
    return TypedDict(name, annotations, total=False)  # type: ignore[operator]
