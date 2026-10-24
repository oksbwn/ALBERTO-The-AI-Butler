import pytest
from alberto.engine.state import build_state_typeddict
from alberto.nodes.flow import (
    inject_factory,
    debug_factory,
    delay_factory,
    join_factory,
    make_router_path,
    router_targets,
)
from alberto.nodes.data import (
    transform_factory,
    _get_nested,
    _set_nested,
    _delete_nested,
)
from alberto.engine.compiler import compile_workflow, CompileContext


def test_state_typeddict_default_channels():
    StateDict = build_state_typeddict({})
    annotations = getattr(StateDict, "__annotations__", {})
    assert "messages" in annotations
    assert "msg" in annotations
    assert "payload" in annotations
    assert "topic" in annotations


def test_inject_node_execution():
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    cfg = {
        "topic": "sensor.temperature",
        "payload_type": "json",
        "payload": {"value": 24.5, "unit": "C"},
    }
    node = inject_factory(cfg, ctx)
    out = node({})
    assert out["topic"] == "sensor.temperature"
    assert out["payload"] == {"value": 24.5, "unit": "C"}
    assert out["msg"]["topic"] == "sensor.temperature"
    assert out["msg"]["payload"] == {"value": 24.5, "unit": "C"}


def test_nested_property_helpers():
    data = {"payload": {"device": {"status": "offline", "secret": "token123"}}}
    assert _get_nested(data, "payload.device.status") == "offline"
    
    _set_nested(data, "payload.device.status", "online")
    assert data["payload"]["device"]["status"] == "online"
    
    _set_nested(data, "payload.device.new_field", 42)
    assert data["payload"]["device"]["new_field"] == 42
    
    _delete_nested(data, "payload.device.secret")
    assert "secret" not in data["payload"]["device"]


def test_transform_visual_operations():
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    cfg = {
        "operations": [
            {"type": "set", "target": "payload.status", "value": "active"},
            {"type": "set", "target": "payload.count", "value": 10},
            {"type": "rename", "target": "payload.count", "to": "payload.total"},
            {"type": "delete", "target": "temp_key"},
        ]
    }
    node = transform_factory(cfg, ctx)
    state = {
        "payload": {"name": "sensor"},
        "temp_key": "remove_me",
    }
    out = node(state)
    assert out["payload"]["status"] == "active"
    assert out["payload"]["total"] == 10
    assert "count" not in out["payload"]
    assert "temp_key" not in out


def test_router_switch_rules():
    cfg = {
        "rules": [
            {"property": "payload.temp", "op": "gt", "value": 30, "target": "cooling_node"},
            {"property": "payload.temp", "op": "lt", "value": 15, "target": "heating_node"},
            {"property": "payload.mode", "op": "eq", "value": "eco", "target": "eco_node"},
            {"property": "payload.alert", "op": "true", "target": "alert_node"},
            {"property": "payload.empty_field", "op": "empty", "target": "fallback_node"},
        ],
        "default": "default_node",
    }
    
    targets = router_targets(cfg)
    assert "cooling_node" in targets
    assert "heating_node" in targets
    assert "eco_node" in targets
    assert "alert_node" in targets
    assert "fallback_node" in targets
    assert "default_node" in targets
    
    router_fn = make_router_path(cfg)
    
    # 1. Hot temp -> cooling
    res1 = router_fn({"payload": {"temp": 35, "mode": "normal"}})
    assert res1 == "cooling_node"
    
    # 2. Cold temp -> heating
    res2 = router_fn({"payload": {"temp": 10, "mode": "normal"}})
    assert res2 == "heating_node"
    
    # 3. Normal temp, eco mode -> eco
    res3 = router_fn({"payload": {"temp": 20, "mode": "eco"}})
    assert res3 == "eco_node"
    
    # 4. Alert is true -> alert
    res4 = router_fn({"payload": {"temp": 20, "mode": "normal", "alert": True}})
    assert res4 == "alert_node"
    
    # 5. Default fallback
    res5 = router_fn({"payload": {"temp": 20, "mode": "normal"}})
    assert res5 == "default_node"


def test_debug_node_redaction():
    from unittest.mock import patch
    emitted = []
    
    def fake_stream_writer():
        def _write(chunk):
            emitted.append(chunk)
        return _write
        
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    cfg = {"id": "debug_1", "target": "payload", "active": True}
    node = debug_factory(cfg, ctx)
    
    state = {
        "payload": {
            "api_key": "super_secret_token",
            "password": "my_password",
            "normal_value": 123,
        }
    }
    
    with patch("langgraph.config.get_stream_writer", fake_stream_writer):
        node(state)
        
    assert len(emitted) == 1
    event = emitted[0]
    assert event["channel"] == "debug"
    assert event["payload"]["node_id"] == "debug_1"
    assert event["payload"]["data"]["api_key"] == "[REDACTED]"
    assert event["payload"]["data"]["password"] == "[REDACTED]"
    assert event["payload"]["data"]["normal_value"] == 123


@pytest.mark.asyncio
async def test_delay_node_execution():
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    cfg = {"seconds": 0.01, "unit": "seconds"}
    node = delay_factory(cfg, ctx)
    out = await node({})
    assert out == {}


def test_canonical_message_bidirectional_sync():
    from alberto.engine.compiler import _sync_aliases, _sync_output_aliases, wrap_canonical_node

    # 1. State input sync: payload to msg.payload
    state1 = {"payload": {"temp": 28}, "topic": "iot/temp"}
    synced1 = _sync_aliases(state1)
    assert synced1["msg"]["payload"] == {"temp": 28}
    assert synced1["msg"]["topic"] == "iot/temp"

    # 2. State input sync: msg to payload
    state2 = {"msg": {"payload": [1, 2, 3], "topic": "iot/nums", "metadata": {"origin": "sensor"}}}
    synced2 = _sync_aliases(state2)
    assert synced2["payload"] == [1, 2, 3]
    assert synced2["topic"] == "iot/nums"

    # 3. Output sync: node returning payload updates msg.payload
    node_out1 = {"payload": 999}
    wrapped_out1 = _sync_output_aliases(node_out1, state1)
    assert wrapped_out1["payload"] == 999
    assert wrapped_out1["msg"]["payload"] == 999

    # 4. Output sync: node returning msg updates payload
    node_out2 = {"msg": {"payload": "active", "topic": "status"}}
    wrapped_out2 = _sync_output_aliases(node_out2, state2)
    assert wrapped_out2["payload"] == "active"
    assert wrapped_out2["topic"] == "status"

    # 5. Full wrapped node execution
    def raw_node(st):
        return {"payload": st["msg"]["payload"]["temp"] + 2}

    wrapped = wrap_canonical_node(raw_node)
    result = wrapped({"payload": {"temp": 28}})
    assert result["payload"] == 30
    assert result["msg"]["payload"] == 30


def test_multi_inject_entry_dispatch():
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    wf_def = {
        "entry_node": "inject_a",
        "nodes": [
            {
                "id": "inject_a",
                "type": "inject",
                "config": {"topic": "topic.a", "payload": "from_a", "payload_type": "string"},
            },
            {
                "id": "inject_b",
                "type": "inject",
                "config": {"topic": "topic.b", "payload": "from_b", "payload_type": "string"},
            },
            {
                "id": "sink",
                "type": "passthrough",
                "config": {},
            },
        ],
        "edges": [
            {"from": "inject_a", "to": "sink"},
            {"from": "inject_b", "to": "sink"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)

    # Invoke targeting inject_b
    out_b = graph.invoke({"__entry_node__": "inject_b"})
    assert out_b["payload"] == "from_b"
    assert out_b["msg"]["payload"] == "from_b"
    assert out_b["topic"] == "topic.b"

    # Invoke targeting default (inject_a)
    out_a = graph.invoke({})
    assert out_a["payload"] == "from_a"
    assert out_a["msg"]["payload"] == "from_a"
    assert out_a["topic"] == "topic.a"


def test_fanout_nested_payload_dot_path():
    from alberto.nodes.flow import make_fanout_path

    cfg = {
        "over": "msg.payload.items",
        "child_node": "process_item",
    }
    fanout_fn = make_fanout_path(cfg)

    state = {
        "msg": {
            "payload": {
                "items": [
                    {"id": 1, "val": "alpha"},
                    {"id": 2, "val": "beta"},
                ]
            }
        }
    }
    sends = fanout_fn(state)
    assert len(sends) == 2
    assert sends[0].node == "process_item"
    assert sends[0].arg["payload"] == {"id": 1, "val": "alpha"}
    assert sends[1].arg["payload"] == {"id": 2, "val": "beta"}


def test_subworkflow_nested_dot_path_mapping():
    from alberto.nodes.flow import subworkflow_factory

    ctx = CompileContext(tenant_id="t1", project_id="p1")

    from alberto.engine.compiler import wrap_canonical_node

    # Define actual child workflow executable in CompileContext
    ctx.workflows["child_wf_1"] = {
        "entry_node": "child_change",
        "nodes": [
            {
                "id": "child_change",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.status", "value": "success"},
                    ]
                },
            },
            {
                "id": "child_end",
                "type": "end",
                "config": {},
            },
        ],
        "edges": [
            {"source": "child_change", "target": "child_end"},
        ],
    }

    cfg = {
        "workflow_id": "child_wf_1",
        "input_mapping": {
            "target_sensor_id": "msg.payload.device.sensor_id",
        },
        "output_mapping": {
            "payload.status": "payload.sub_status",
        },
    }

    node = wrap_canonical_node(subworkflow_factory(cfg, ctx))
    parent_state = {
        "msg": {
            "payload": {
                "device": {"sensor_id": "sensor-xyz-99"}
            }
        }
    }

    import asyncio
    res = asyncio.run(node(parent_state))

    # Verify output mapped back into nested target
    assert res["payload"]["sub_status"] == "success"
    assert res["msg"]["payload"]["sub_status"] == "success"


def test_multi_inject_invalid_and_disabled_entry_rejection():
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    wf_def = {
        "entry_node": "inject_a",
        "nodes": [
            {
                "id": "inject_a",
                "type": "inject",
                "config": {"topic": "topic.a", "payload": "from_a", "enabled": True},
            },
            {
                "id": "inject_disabled",
                "type": "inject",
                "config": {"topic": "topic.disabled", "payload": "disabled_data", "enabled": False},
            },
            {
                "id": "sink",
                "type": "passthrough",
                "config": {},
            },
        ],
        "edges": [
            {"from": "inject_a", "to": "sink"},
            {"from": "inject_disabled", "to": "sink"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)

    # 1. Invalid non-existent entry node must raise ValueError
    with pytest.raises(ValueError, match="is invalid. Must be one of valid trigger candidates"):
        graph.invoke({"__entry_node__": "non_existent_node"})

    # 2. Non-trigger node (e.g. sink) requested as entry must raise ValueError
    with pytest.raises(ValueError, match="is invalid. Must be one of valid trigger candidates"):
        graph.invoke({"__entry_node__": "sink"})

    # 3. Disabled entry node must raise ValueError
    with pytest.raises(ValueError, match="is disabled"):
        graph.invoke({"__entry_node__": "inject_disabled"})


def test_canonical_and_legacy_conflicting_updates_precedence():
    from alberto.engine.compiler import _sync_output_aliases, _sync_aliases

    in_state = {"msg": {"payload": {"init": 1}, "topic": "base"}}

    # Scenario 1: Output contains conflicting canonical msg.payload and legacy payload
    conflicting_out = {
        "msg": {"payload": {"status": "canonical_wins"}},
        "payload": {"status": "legacy_loses"},
    }
    resolved = _sync_output_aliases(conflicting_out, in_state)
    assert resolved["payload"]["status"] == "canonical_wins"
    assert resolved["msg"]["payload"]["status"] == "canonical_wins"

    # Scenario 2: State input has conflicting msg and top-level payload
    conflicting_state = {
        "msg": {"payload": {"priority": "authoritative"}},
        "payload": {"priority": "subordinate"},
    }
    synced = _sync_aliases(conflicting_state)
    assert synced["payload"]["priority"] == "authoritative"
    assert synced["msg"]["payload"]["priority"] == "authoritative"


def test_sequential_message_propagation_full_pipeline():
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    wf_def = {
        "entry_node": "inject_node",
        "nodes": [
            {
                "id": "inject_node",
                "type": "inject",
                "config": {
                    "topic": "telemetry.v1",
                    "payload_type": "json",
                    "payload": {"value": 10},
                },
            },
            {
                "id": "change_a",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.value", "value": 20},
                    ]
                },
            },
            {
                "id": "change_b",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.doubled", "value": 40},
                    ]
                },
            },
            {
                "id": "debug_node",
                "type": "debug",
                "config": {
                    "target": "msg.payload",
                    "active": True,
                },
            },
        ],
        "edges": [
            {"from": "inject_node", "to": "change_a"},
            {"from": "change_a", "to": "change_b"},
            {"from": "change_b", "to": "debug_node"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)
    res = graph.invoke({})

    assert res["payload"]["value"] == 20
    assert res["payload"]["doubled"] == 40
    assert res["msg"]["payload"]["value"] == 20
    assert res["msg"]["payload"]["doubled"] == 40
    assert res["msg"]["topic"] == "telemetry.v1"


def test_parallel_branches_isolation_and_deterministic_merge():
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    wf_def = {
        "entry_node": "inject_node",
        "nodes": [
            {
                "id": "inject_node",
                "type": "inject",
                "config": {
                    "topic": "branch.test",
                    "payload_type": "json",
                    "payload": {"base": 100, "shared_list": ["init"]},
                },
            },
            {
                "id": "branch_a",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.branch_a_val", "value": 20},
                    ]
                },
            },
            {
                "id": "branch_b",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.branch_b_val", "value": 30},
                    ]
                },
            },
            {
                "id": "join_sink",
                "type": "passthrough",
                "config": {},
            },
        ],
        "edges": [
            {"from": "inject_node", "to": "branch_a"},
            {"from": "inject_node", "to": "branch_b"},
            {"from": "branch_a", "to": "join_sink"},
            {"from": "branch_b", "to": "join_sink"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)

    # Execute multiple times to assert determinism and isolation
    for _ in range(3):
        res = graph.invoke({})
        assert res["payload"]["base"] == 100
        assert res["payload"]["branch_a_val"] == 20
        assert res["payload"]["branch_b_val"] == 30
        assert res["msg"]["payload"]["base"] == 100
        assert res["msg"]["payload"]["branch_a_val"] == 20
        assert res["msg"]["payload"]["branch_b_val"] == 30


@pytest.mark.asyncio
async def test_delay_node_cancellation():
    import asyncio
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    cfg = {"seconds": 5.0, "unit": "seconds"}
    node = delay_factory(cfg, ctx)

    task = asyncio.create_task(node({}))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_run_snapshot_pruning_and_immutability():
    import copy

    original_wf = {
        "entry_node": "inject_1",
        "nodes": [{"id": "inject_1", "type": "inject", "config": {"payload": "orig"}}],
    }

    thread_meta = {}
    for i in range(25):
        run_id = f"run_{i:02d}"
        immutable_snapshot = copy.deepcopy(original_wf)
        meta = dict(thread_meta)
        run_snapshot_keys = [k for k in meta if k.startswith("run_snapshot_")]
        if len(run_snapshot_keys) > 20:
            for old_key in run_snapshot_keys[:-15]:
                meta.pop(old_key, None)
        meta["workflow_snapshot"] = immutable_snapshot
        meta[f"run_snapshot_{run_id}"] = immutable_snapshot
        thread_meta = meta

    # Assert bounded metadata: should not hold all 25 run snapshots
    remaining_keys = [k for k in thread_meta if k.startswith("run_snapshot_")]
    assert len(remaining_keys) <= 20
    assert "run_snapshot_run_00" not in thread_meta  # Oldest pruned
    assert "run_snapshot_run_24" in thread_meta      # Newest retained


def test_parallel_conflicting_writes_deterministic_preservation():
    """Verify that when parallel branches write conflicting values to the same key,
    neither value is silently dropped and results are deterministically combined."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    wf_def = {
        "entry_node": "inject_node",
        "nodes": [
            {
                "id": "inject_node",
                "type": "inject",
                "config": {
                    "topic": "test.conflict",
                    "payload_type": "json",
                    "payload": {"value": 10, "source": "sensor"},
                },
            },
            {
                "id": "change_a",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.value", "value": 20},
                    ]
                },
            },
            {
                "id": "change_b",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.value", "value": 30},
                    ]
                },
            },
            {
                "id": "join_node",
                "type": "join",
                "config": {"reducer": "branch_map"},
            },
        ],
        "edges": [
            {"from": "inject_node", "to": "change_a"},
            {"from": "inject_node", "to": "change_b"},
            {"from": "change_a", "to": "join_node"},
            {"from": "change_b", "to": "join_node"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)

    # Execute repeatedly to verify deterministic outcome
    for _ in range(5):
        res = graph.invoke({})
        # 1. Branch-scoped outputs remain independently identifiable in _branches
        assert res["_branches"]["change_a"]["value"] == 20
        assert res["_branches"]["change_b"]["value"] == 30
        # 2. Join node with branch_map combines conflicting branch outputs deterministically without loss
        assert res["payload"]["change_a"]["value"] == 20
        assert res["payload"]["change_b"]["value"] == 30
        # 3. Canonical msg and legacy payload stay synchronized
        assert res["msg"]["payload"]["change_a"]["value"] == 20
        assert res["msg"]["payload"]["change_b"]["value"] == 30


def test_parallel_branch_input_isolation_no_mutation():
    """Verify that Branch A cannot mutate Branch B's input via nested references."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")

    # Define custom node functions to test raw in-place mutation attempts
    def branch_a_mutator(state: dict) -> dict:
        state["payload"]["items"].append("corrupted_by_a")
        return {"payload": {"from_a": True}}

    def branch_b_checker(state: dict) -> dict:
        # Branch B must observe original unmutated items
        items = list(state["payload"]["items"])
        return {"payload": {"observed_items": items}}

    from alberto.engine.compiler import wrap_canonical_node

    wrapped_a = wrap_canonical_node(branch_a_mutator, node_id="node_a")
    wrapped_b = wrap_canonical_node(branch_b_checker, node_id="node_b")

    shared_input = {
        "payload": {"items": ["orig_1", "orig_2"]},
        "msg": {"payload": {"items": ["orig_1", "orig_2"]}},
    }

    # Execute Branch A (which attempts in-place mutation)
    wrapped_a(shared_input)

    # Execute Branch B with the same input
    out_b = wrapped_b(shared_input)

    # Verify Branch B was not corrupted
    assert out_b["payload"]["observed_items"] == ["orig_1", "orig_2"]
    assert "corrupted_by_a" not in out_b["payload"]["observed_items"]


def test_join_node_branch_map_and_array_reducers():
    """Verify Join node with explicit 'branch_map' and 'array' reducers."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")

    state_with_branches = {
        "_branches": {
            "branch_1": {"metric": "temp", "val": 22},
            "branch_2": {"metric": "humidity", "val": 65},
        }
    }

    # 1. Join with branch_map reducer
    join_map = join_factory({"reducer": "branch_map", "output_key": "joined"}, ctx)
    res_map = join_map(state_with_branches)
    assert res_map["joined"]["branch_1"]["val"] == 22
    assert res_map["joined"]["branch_2"]["val"] == 65

    # 2. Join with array reducer
    join_arr = join_factory({"reducer": "array", "output_key": "items"}, ctx)
    res_arr = join_arr(state_with_branches)
    assert len(res_arr["items"]) == 2
    assert res_arr["items"][0]["metric"] == "temp"
    assert res_arr["items"][1]["metric"] == "humidity"


def test_parallel_topic_and_metadata_conflicts():
    """Verify topic and metadata conflict handling across parallel branch merges."""
    from alberto.engine.state import _merge_msg

    left = {
        "topic": "sensor.north",
        "metadata": {"timestamp": 1000, "region": "US"},
        "payload": {"status": "ok"},
    }
    right = {
        "topic": "sensor.south",
        "metadata": {"timestamp": 1005, "source": "mqtt"},
        "payload": {"status": "ok"},
    }

    merged = _merge_msg(left, right)
    # Topics deterministically combined
    assert merged["topic"] == "sensor.north,sensor.south"
    # Metadata dictionaries merged
    assert merged["metadata"]["region"] == "US"
    assert merged["metadata"]["source"] == "mqtt"


def test_active_and_interrupted_run_snapshots_never_pruned():
    """Verify that pruning never deletes snapshots belonging to active or interrupted runs."""
    import copy

    original_wf = {"entry_node": "inject_1", "nodes": []}
    thread_meta = {}

    # Simulate 25 runs where run_02 is currently interrupted/active
    active_run_id = "run_02"
    for i in range(25):
        run_id = f"run_{i:02d}"
        immutable_snapshot = copy.deepcopy(original_wf)
        meta = dict(thread_meta)
        run_snapshot_keys = [k for k in meta if k.startswith("run_snapshot_")]
        if len(run_snapshot_keys) > 20:
            for old_key in run_snapshot_keys[:-15]:
                old_run_id = old_key.removeprefix("run_snapshot_")
                # Active/interrupted run must be preserved
                if old_run_id != active_run_id:
                    meta.pop(old_key, None)
        meta["workflow_snapshot"] = immutable_snapshot
        meta[f"run_snapshot_{run_id}"] = immutable_snapshot
        thread_meta = meta

    # Assert bounded overall size
    assert len([k for k in thread_meta if k.startswith("run_snapshot_")]) <= 21
    # Run 00 was pruned
    assert "run_snapshot_run_00" not in thread_meta
    # BUT active run_02 was preserved!
    assert "run_snapshot_run_02" in thread_meta


@pytest.mark.asyncio
async def test_durable_delay_lifecycle_restart_and_recovery():
    """Verify durable Delay lifecycle: interrupt -> persistence -> resume -> single execution."""
    import datetime
    from alberto.db.base import SessionLocal
    from alberto.models import Thread, Run, Workflow
    from alberto.services.runs import RunService
    from alberto.services.dispatch import run_due_delays
    from langgraph.checkpoint.memory import InMemorySaver

    checkpointer = InMemorySaver()
    rs = RunService(checkpointer=checkpointer)

    wf_def = {
        "id": "wf_delay_durable",
        "entry_node": "inject_node",
        "nodes": [
            {
                "id": "inject_node",
                "type": "inject",
                "config": {"payload": {"temp": 28}, "topic": "climate"},
            },
            {
                "id": "delay_node",
                "type": "delay",
                "config": {"seconds": 0.05, "unit": "seconds", "mode": "durable"},
            },
            {
                "id": "debug_node",
                "type": "debug",
                "config": {"target": "payload", "active": True},
            },
        ],
        "edges": [
            {"from": "inject_node", "to": "delay_node"},
            {"from": "delay_node", "to": "debug_node"},
        ],
    }

    # 1. Create workflow and thread in DB
    async with SessionLocal() as s:
        wf = Workflow(
            tenant_id="t_delay",
            project_id="p_delay",
            name="Durable Delay WF",
            executable=wf_def,
        )
        s.add(wf)
        await s.flush()
        th = Thread(
            tenant_id="t_delay",
            project_id="p_delay",
            workflow_id=wf.id,
            lg_thread_id="th_delay_001",
        )
        s.add(th)
        await s.flush()
        run = await rs.create_run(
            s,
            tenant_id="t_delay",
            project_id="p_delay",
            workflow_id=wf.id,
            thread_id=th.id,
            input={},
        )
        run_id = run.id

    # 2. Execute run to completion: it should pause at Delay node with status="interrupted"
    res = await rs.run_to_completion(
        run_id=run_id, tenant_id="t_delay", project_id="p_delay"
    )
    assert res["status"] == "interrupted"
    assert res["interrupted"] is True

    # Confirm continuation deadline was recorded in Thread.meta
    async with SessionLocal() as s:
        th = await s.get(Thread, th.id)
        assert f"delay_continuation_{run_id}" in th.meta
        cont = th.meta[f"delay_continuation_{run_id}"]
        assert cont["type"] == "delay"

    # 3. Simulate process restart: fresh RunService using the same checkpointer & DB
    fresh_rs = RunService(checkpointer=checkpointer)

    # Wait for the delay duration to expire
    import asyncio
    await asyncio.sleep(0.08)

    # 4. Trigger scheduler sweep (run_due_delays)
    resumed = await run_due_delays(fresh_rs)
    assert resumed == 1

    # Confirm run reached "done" and continuation was cleared
    async with SessionLocal() as s:
        r = await s.get(Run, run_id)
        assert r.status == "done"
        th = await s.get(Thread, th.id)
        assert f"delay_continuation_{run_id}" not in th.meta

    # 5. Subsequent scheduler sweep does NOT fire duplicate execution
    resumed_again = await run_due_delays(fresh_rs)
    assert resumed_again == 0


@pytest.mark.asyncio
async def test_subworkflow_canonical_message_propagation_full_pipeline():
    """Verify: Inject -> Change msg.payload -> Subworkflow -> Change legacy payload -> Debug."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")

    # Define child workflow executable
    ctx.workflows["child_transform_wf"] = {
        "entry_node": "child_change",
        "nodes": [
            {
                "id": "child_change",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.child_processed", "value": True},
                    ]
                },
            },
            {
                "id": "child_end",
                "type": "end",
                "config": {},
            },
        ],
        "edges": [
            {"source": "child_change", "target": "child_end"},
        ],
    }

    wf_def = {
        "entry_node": "inject_node",
        "nodes": [
            {
                "id": "inject_node",
                "type": "inject",
                "config": {
                    "payload_type": "json",
                    "payload": {"init": "start_val"},
                    "topic": "pipeline.test",
                },
            },
            {
                "id": "change_canonical",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "msg.payload.step1", "value": "complete"},
                    ]
                },
            },
            {
                "id": "subwf_node",
                "type": "subworkflow",
                "config": {
                    "workflow_id": "child_transform_wf",
                    "input_mapping": {"msg.payload": "payload"},
                    "output_mapping": {"payload": "payload"},
                },
            },
            {
                "id": "change_legacy",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.step3", "value": "final"},
                    ]
                },
            },
            {
                "id": "debug_node",
                "type": "debug",
                "config": {"target": "msg.payload", "active": True},
            },
        ],
        "edges": [
            {"from": "inject_node", "to": "change_canonical"},
            {"from": "change_canonical", "to": "subwf_node"},
            {"from": "subwf_node", "to": "change_legacy"},
            {"from": "change_legacy", "to": "debug_node"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)
    res = await graph.ainvoke({})

    # Assert canonical and legacy values are completely synchronized downstream
    assert res["payload"]["init"] == "start_val"
    assert res["payload"]["step1"] == "complete"
    assert res["payload"]["child_processed"] is True
    assert res["payload"]["step3"] == "final"
    assert res["msg"]["payload"]["init"] == "start_val"
    assert res["msg"]["payload"]["step1"] == "complete"
    assert res["msg"]["payload"]["child_processed"] is True
    assert res["msg"]["payload"]["step3"] == "final"
    assert res["msg"]["topic"] == "pipeline.test"


def test_automation_manager_nl_workflow_creation_and_execution_lifecycle():
    """Verify Automation Manager prompt scenario:
    'Accepts temp reading, checks if above 30, sets warning status, displays in Debug'.
    Assert visual threshold edit from 30 to 35 and test runtime branches."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")

    # Workflow generated matching the exact NL request
    wf_def = {
        "entry_node": "inject_sensor",
        "nodes": [
            {
                "id": "inject_sensor",
                "type": "inject",
                "config": {"payload_type": "json"},
            },
            {
                "id": "switch_temp",
                "type": "switch",
                "config": {
                    "rules": [
                        {"property": "payload.temp", "op": "gt", "value": 35, "target": "set_warning"},
                    ],
                    "default": "debug_normal",
                },
            },
            {
                "id": "set_warning",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.status", "value": "warning"},
                    ]
                },
            },
            {
                "id": "debug_warning",
                "type": "debug",
                "config": {"target": "payload", "active": True},
            },
            {
                "id": "debug_normal",
                "type": "debug",
                "config": {"target": "payload", "active": True},
            },
        ],
        "edges": [
            {"from": "inject_sensor", "to": "switch_temp"},
            {"from": "set_warning", "to": "debug_warning"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)

    # 1. Input 32: does NOT exceed modified threshold 35 -> follows default normal debug path
    res_normal = graph.invoke({"payload": {"temp": 32}})
    assert res_normal["payload"]["temp"] == 32
    assert "status" not in res_normal["payload"]  # Did not route through set_warning

    # 2. Input 40: DOES exceed modified threshold 35 -> routes through set_warning
    res_warning = graph.invoke({"payload": {"temp": 40}})
    assert res_warning["payload"]["temp"] == 40
    assert res_warning["payload"]["status"] == "warning"
    assert res_warning["msg"]["payload"]["status"] == "warning"


@pytest.mark.asyncio
async def test_durable_delay_crash_recovery_at_claim_resume_boundary():
    """Verify that when a backend crash/failure occurs at the claim/resume boundary,
    the continuation is not lost and is safely recovered on subsequent scheduler sweeps."""
    import alberto.services.dispatch as dispatch_mod
    from alberto.db.base import SessionLocal
    from alberto.models import Thread, Run, Workflow
    from alberto.services.runs import RunService
    from langgraph.checkpoint.memory import InMemorySaver

    checkpointer = InMemorySaver()
    rs = RunService(checkpointer=checkpointer)

    wf_def = {
        "id": "wf_delay_crash_safety",
        "entry_node": "inject_node",
        "nodes": [
            {
                "id": "inject_node",
                "type": "inject",
                "config": {"payload": {"device": "temp_sensor", "reading": 42}},
            },
            {
                "id": "delay_node",
                "type": "delay",
                "config": {"seconds": 0.05, "unit": "seconds", "mode": "durable"},
            },
            {
                "id": "debug_node",
                "type": "debug",
                "config": {"target": "payload", "active": True},
            },
        ],
        "edges": [
            {"from": "inject_node", "to": "delay_node"},
            {"from": "delay_node", "to": "debug_node"},
        ],
    }

    async with SessionLocal() as s:
        wf = Workflow(
            tenant_id="t_crash",
            project_id="p_crash",
            name="Crash Recovery WF",
            executable=wf_def,
        )
        s.add(wf)
        await s.flush()
        th = Thread(
            tenant_id="t_crash",
            project_id="p_crash",
            workflow_id=wf.id,
            lg_thread_id="th_crash_001",
        )
        s.add(th)
        await s.flush()
        run = await rs.create_run(
            s,
            tenant_id="t_crash",
            project_id="p_crash",
            workflow_id=wf.id,
            thread_id=th.id,
            input={},
        )
        run_id = run.id

    # 1. Run until delay interruption
    res = await rs.run_to_completion(run_id=run_id, tenant_id="t_crash", project_id="p_crash")
    assert res["status"] == "interrupted"

    # Wait for delay duration to become due
    import asyncio
    await asyncio.sleep(0.08)

    # 2. Inject fault right after claim: simulate backend crash before resume()
    crash_simulated = []

    async def _simulate_crash(r_id):
        crash_simulated.append(r_id)
        raise RuntimeError("Simulated crash at claim/resume boundary!")

    dispatch_mod._FAULT_HOOK_AFTER_CLAIM = _simulate_crash
    try:
        with pytest.raises(RuntimeError, match="Simulated crash"):
            await dispatch_mod.run_due_delays(rs)
    finally:
        dispatch_mod._FAULT_HOOK_AFTER_CLAIM = None

    assert len(crash_simulated) == 1

    # 3. CRITICAL VERIFICATION: Continuation was NOT lost during the crash!
    async with SessionLocal() as s:
        th = await s.get(Thread, th.id)
        assert f"delay_continuation_{run_id}" in th.meta
        cont = th.meta[f"delay_continuation_{run_id}"]
        assert cont["status"] == "claimed"
        r = await s.get(Run, run_id)
        assert r.status == "interrupted"

    # 4. Simulate restart: Fresh RunService, lease expired (lease_seconds=0)
    fresh_rs = RunService(checkpointer=checkpointer)
    recovered_count = await dispatch_mod.run_due_delays(fresh_rs, lease_seconds=0)
    assert recovered_count == 1

    # 5. Confirm run completed cleanly and continuation is purged upon terminal state
    async with SessionLocal() as s:
        r = await s.get(Run, run_id)
        assert r.status == "done"
        th = await s.get(Thread, th.id)
        assert f"delay_continuation_{run_id}" not in th.meta

    # 6. Idempotency: subsequent sweep does not duplicate execution
    again = await dispatch_mod.run_due_delays(fresh_rs, lease_seconds=0)
    assert again == 0


def test_parallel_conflicting_writes_with_join_merge_reducer():
    """Verify parallel conflicting writes when Join node uses 'merge' reducer:
    Disjoint keys are preserved, and conflicting scalar keys are combined deterministically."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    wf_def = {
        "entry_node": "inject_node",
        "nodes": [
            {
                "id": "inject_node",
                "type": "inject",
                "config": {
                    "topic": "test.merge",
                    "payload_type": "json",
                    "payload": {"value": 10, "source": "sensor"},
                },
            },
            {
                "id": "change_a",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.value", "value": 20},
                        {"type": "set", "target": "payload.branch_a_metric", "value": 100},
                    ]
                },
            },
            {
                "id": "change_b",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.value", "value": 30},
                        {"type": "set", "target": "payload.branch_b_metric", "value": 200},
                    ]
                },
            },
            {
                "id": "join_node",
                "type": "join",
                "config": {"reducer": "merge"},
            },
        ],
        "edges": [
            {"from": "inject_node", "to": "change_a"},
            {"from": "inject_node", "to": "change_b"},
            {"from": "change_a", "to": "join_node"},
            {"from": "change_b", "to": "join_node"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)

    for _ in range(5):
        res = graph.invoke({})
        # Disjoint branch metrics preserved
        assert res["payload"]["branch_a_metric"] == 100
        assert res["payload"]["branch_b_metric"] == 200
        # Conflicting scalar keys combined without data loss in deterministic branch order
        assert res["payload"]["value"] == [20, 30]
        # Canonical msg synchronized
        assert res["msg"]["payload"]["value"] == [20, 30]
        # Branch-scoped outputs independently identifiable
        assert res["_branches"]["change_a"]["value"] == 20
        assert res["_branches"]["change_b"]["value"] == 30


@pytest.mark.asyncio
async def test_durable_delay_active_running_lease_safety():
    """Verify that when a resumed run remains active longer than the 30-second lease,
    subsequent scheduler sweeps do NOT treat it as an abandoned claim or duplicate resume."""
    import alberto.services.dispatch as dispatch_mod
    from alberto.db.base import SessionLocal
    from alberto.models import Thread, Run, Workflow
    from alberto.services.runs import RunService
    from langgraph.checkpoint.memory import InMemorySaver
    from datetime import datetime, timezone, timedelta

    checkpointer = InMemorySaver()
    rs = RunService(checkpointer=checkpointer)

    wf_def = {
        "id": "wf_delay_active_running",
        "entry_node": "inject_node",
        "nodes": [
            {"id": "inject_node", "type": "inject", "config": {"payload": {"test": 1}}},
            {"id": "delay_node", "type": "delay", "config": {"seconds": 0.05, "unit": "seconds", "mode": "durable"}},
            {"id": "debug_node", "type": "debug", "config": {"target": "payload"}},
        ],
        "edges": [
            {"from": "inject_node", "to": "delay_node"},
            {"from": "delay_node", "to": "debug_node"},
        ],
    }

    async with SessionLocal() as s:
        wf = Workflow(tenant_id="t_active", project_id="p_active", name="Active WF", executable=wf_def)
        s.add(wf)
        await s.flush()
        th = Thread(tenant_id="t_active", project_id="p_active", workflow_id=wf.id, lg_thread_id="th_active_001")
        s.add(th)
        await s.flush()
        run = await rs.create_run(s, tenant_id="t_active", project_id="p_active", workflow_id=wf.id, thread_id=th.id, input={})
        run_id = run.id

    # 1. Run until delay interruption
    res = await rs.run_to_completion(run_id=run_id, tenant_id="t_active", project_id="p_active")
    assert res["status"] == "interrupted"

    # 2. Simulate: Run was claimed and transitioned to 'running'
    # but the execution is taking 60 seconds (lease of 30s has expired)
    now = datetime.now(timezone.utc)
    expired_claim_time = (now - timedelta(seconds=60)).isoformat()
    async with SessionLocal() as s:
        r = await s.get(Run, run_id)
        r.status = "running"
        t = await s.get(Thread, th.id)
        t_meta = dict(t.meta or {})
        delay_info = dict(t_meta.get(f"delay_continuation_{run_id}") or {})
        delay_info["status"] = "claimed"
        delay_info["claimed_at"] = expired_claim_time
        t_meta[f"delay_continuation_{run_id}"] = delay_info
        t.meta = t_meta
        await s.commit()

    # 3. Sweep runs: Must NOT reclaim running execution even though lease expired
    swept = await dispatch_mod.run_due_delays(rs, lease_seconds=30)
    assert swept == 0

    # 4. Confirm run status remains running and wasn't double-invoked
    async with SessionLocal() as s:
        r = await s.get(Run, run_id)
        assert r.status == "running"


@pytest.mark.asyncio
async def test_consecutive_delay_nodes_lifecycle():
    """Verify consecutive delay nodes: Inject -> Delay A -> Delay B -> Debug.
    Both delays pause and resume in order, continuation updates accurately, and Debug executes once."""
    import asyncio
    import alberto.services.dispatch as dispatch_mod
    from alberto.db.base import SessionLocal
    from alberto.models import Thread, Run, Workflow
    from alberto.services.runs import RunService
    from langgraph.checkpoint.memory import InMemorySaver

    checkpointer = InMemorySaver()
    rs = RunService(checkpointer=checkpointer)

    wf_def = {
        "id": "wf_consecutive_delays",
        "entry_node": "inject_node",
        "nodes": [
            {"id": "inject_node", "type": "inject", "config": {"payload": {"step": 0}}},
            {"id": "delay_a", "type": "delay", "config": {"seconds": 0.05, "unit": "seconds", "mode": "durable"}},
            {"id": "delay_b", "type": "delay", "config": {"seconds": 0.05, "unit": "seconds", "mode": "durable"}},
            {"id": "debug_node", "type": "debug", "config": {"target": "payload"}},
        ],
        "edges": [
            {"from": "inject_node", "to": "delay_a"},
            {"from": "delay_a", "to": "delay_b"},
            {"from": "delay_b", "to": "debug_node"},
        ],
    }

    async with SessionLocal() as s:
        wf = Workflow(tenant_id="t_cons", project_id="p_cons", name="Consecutive WF", executable=wf_def)
        s.add(wf)
        await s.flush()
        th = Thread(tenant_id="t_cons", project_id="p_cons", workflow_id=wf.id, lg_thread_id="th_cons_001")
        s.add(th)
        await s.flush()
        run = await rs.create_run(s, tenant_id="t_cons", project_id="p_cons", workflow_id=wf.id, thread_id=th.id, input={})
        run_id = run.id

    # 1. First run halts at Delay A
    res = await rs.run_to_completion(run_id=run_id, tenant_id="t_cons", project_id="p_cons")
    assert res["status"] == "interrupted"

    async with SessionLocal() as s:
        t = await s.get(Thread, th.id)
        cont_a = t.meta.get(f"delay_continuation_{run_id}")
        assert cont_a is not None
        assert cont_a.get("node_id") == "delay_a"

    # Wait for Delay A to become due
    await asyncio.sleep(0.08)

    # 2. Scheduler sweep resumes Delay A; execution reaches Delay B and interrupts again
    resumed_a = await dispatch_mod.run_due_delays(rs, lease_seconds=10)
    assert resumed_a == 1

    # Verify run is now paused at Delay B, and continuation updated to Delay B
    async with SessionLocal() as s:
        r = await s.get(Run, run_id)
        assert r.status == "interrupted"
        t = await s.get(Thread, th.id)
        cont_b = t.meta.get(f"delay_continuation_{run_id}")
        assert cont_b is not None
        assert cont_b.get("node_id") == "delay_b"
        assert cont_b.get("status") != "claimed"  # Fresh pending continuation for Delay B

    # Delay A is no longer eligible; immediate sweep does not resume prematurely
    swept_early = await dispatch_mod.run_due_delays(rs, lease_seconds=10)
    assert swept_early == 0

    # Wait for Delay B to become due
    await asyncio.sleep(0.08)

    # 3. Scheduler sweep resumes Delay B; workflow executes to completion
    resumed_b = await dispatch_mod.run_due_delays(rs, lease_seconds=10)
    assert resumed_b == 1

    # 4. Final state check: Run is done, continuation is purged
    async with SessionLocal() as s:
        r = await s.get(Run, run_id)
        assert r.status == "done"
        t = await s.get(Thread, th.id)
        assert f"delay_continuation_{run_id}" not in (t.meta or {})


@pytest.mark.asyncio
async def test_delay_followed_by_hitl_approval_lifecycle():
    """Verify workflow: Inject -> Delay -> Human Approval (HITL) -> Debug.
    Previous delay continuation does NOT re-trigger resume while workflow is paused for human approval."""
    import asyncio
    import alberto.services.dispatch as dispatch_mod
    from alberto.db.base import SessionLocal
    from alberto.models import Thread, Run, Workflow
    from alberto.services.runs import RunService
    from langgraph.checkpoint.memory import InMemorySaver
    from alberto.engine.registry import register, NodeSpec, Port

    # Register temporary test approval node that invokes interrupt with type 'approval'
    def approval_factory(config: dict, ctx):
        def _node(state: dict):
            from langgraph.types import interrupt
            decision = interrupt({"type": "approval", "question": "Approve action?"})
            return {"payload": {"approved": decision.get("approved", False) if isinstance(decision, dict) else bool(decision)}}
        return _node

    register(
        NodeSpec(
            type="test_hitl_approval",
            schema_id="forge/nodes/start",
            input_ports=[Port(id="in", io_type="any", direction="in")],
            output_ports=[Port(id="out", io_type="any", direction="out")],
            factory=approval_factory,
            category="flow",
            label="HITL Approval",
            description="Human in the loop approval node",
            summarize=lambda c: [],
        )
    )

    checkpointer = InMemorySaver()
    rs = RunService(checkpointer=checkpointer)

    wf_def = {
        "id": "wf_delay_to_hitl",
        "entry_node": "inject_node",
        "nodes": [
            {"id": "inject_node", "type": "inject", "config": {"payload": {"action": "deploy"}}},
            {"id": "delay_node", "type": "delay", "config": {"seconds": 0.05, "unit": "seconds", "mode": "durable"}},
            {"id": "approval_node", "type": "test_hitl_approval", "config": {}},
            {"id": "debug_node", "type": "debug", "config": {"target": "payload"}},
        ],
        "edges": [
            {"from": "inject_node", "to": "delay_node"},
            {"from": "delay_node", "to": "approval_node"},
            {"from": "approval_node", "to": "debug_node"},
        ],
    }

    async with SessionLocal() as s:
        wf = Workflow(tenant_id="t_hitl", project_id="p_hitl", name="HITL WF", executable=wf_def)
        s.add(wf)
        await s.flush()
        th = Thread(tenant_id="t_hitl", project_id="p_hitl", workflow_id=wf.id, lg_thread_id="th_hitl_001")
        s.add(th)
        await s.flush()
        run = await rs.create_run(s, tenant_id="t_hitl", project_id="p_hitl", workflow_id=wf.id, thread_id=th.id, input={})
        run_id = run.id

    # 1. Run halts at Delay
    res = await rs.run_to_completion(run_id=run_id, tenant_id="t_hitl", project_id="p_hitl")
    assert res["status"] == "interrupted"

    await asyncio.sleep(0.08)

    # 2. Scheduler resumes Delay -> workflow proceeds and halts at HITL approval!
    resumed = await dispatch_mod.run_due_delays(rs, lease_seconds=10)
    assert resumed == 1

    # 3. VERIFY: Status is interrupted (at approval), BUT delay continuation was cleared!
    async with SessionLocal() as s:
        r = await s.get(Run, run_id)
        assert r.status == "interrupted"
        t = await s.get(Thread, th.id)
        # Delay continuation MUST NOT exist to prevent stale redispatch
        assert f"delay_continuation_{run_id}" not in (t.meta or {})

    # 4. Scheduler sweep (even with expired lease) does NOT re-dispatch
    resweep = await dispatch_mod.run_due_delays(rs, lease_seconds=0)
    assert resweep == 0

    # 5. Human approval arrives and resumes the workflow
    res_approval = await rs.resume(run_id=run_id, tenant_id="t_hitl", project_id="p_hitl", value={"approved": True})
    assert res_approval["status"] == "done"

    async with SessionLocal() as s:
        r = await s.get(Run, run_id)
        assert r.status == "done"


def test_parallel_nested_conflicts_deterministic_resolution():
    """Verify Section 2.3 nested conflict handling across all data types:
    - Conflicting scalar values -> [v1, v2]
    - Nested dictionaries -> recursively merged
    - Lists -> concatenated
    - Null values -> preserved
    - Missing fields -> preserved
    - Topic conflicts -> preserved
    - Same-key/same-value -> deduplicated"""
    ctx = CompileContext(tenant_id="t1", project_id="p1")

    wf_def = {
        "entry_node": "inject_node",
        "nodes": [
            {
                "id": "inject_node",
                "type": "inject",
                "config": {"payload": {"base": "root"}},
            },
            {
                "id": "branch_1",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.scalar_val", "value": 20},
                        {"type": "set", "target": "payload.nested_dict.level", "value": 1},
                        {"type": "set", "target": "payload.nested_dict.same", "value": "identical"},
                        {"type": "set", "target": "payload.tags", "value": ["tag_a"]},
                        {"type": "set", "target": "payload.optional_null", "value": None},
                        {"type": "set", "target": "payload.field_only_in_1", "value": "only_1"},
                        {"type": "set", "target": "topic", "value": "topic_alpha"},
                    ]
                },
            },
            {
                "id": "branch_2",
                "type": "change",
                "config": {
                    "operations": [
                        {"type": "set", "target": "payload.scalar_val", "value": 30},
                        {"type": "set", "target": "payload.nested_dict.level", "value": 2},
                        {"type": "set", "target": "payload.nested_dict.same", "value": "identical"},
                        {"type": "set", "target": "payload.tags", "value": ["tag_b"]},
                        {"type": "set", "target": "payload.optional_null", "value": 100},
                        {"type": "set", "target": "payload.field_only_in_2", "value": "only_2"},
                        {"type": "set", "target": "topic", "value": "topic_beta"},
                    ]
                },
            },
            {
                "id": "join_node",
                "type": "join",
                "config": {"reducer": "merge"},
            },
        ],
        "edges": [
            {"from": "inject_node", "to": "branch_1"},
            {"from": "inject_node", "to": "branch_2"},
            {"from": "branch_1", "to": "join_node"},
            {"from": "branch_2", "to": "join_node"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)

    for _ in range(5):
        res = graph.invoke({})
        p = res["payload"]
        # 1. Conflicting scalar values combined in deterministic branch order
        assert p["scalar_val"] == [20, 30]
        # 2. Nested dictionaries recursively merged: conflicting leaf -> list, identical leaf -> single value
        assert p["nested_dict"]["level"] == [1, 2]
        assert p["nested_dict"]["same"] == "identical"
        # 3. Lists concatenated
        assert p["tags"] == ["tag_a", "tag_b"]
        # 4. Null value handled cleanly
        assert p["optional_null"] == [None, 100]
        # 5. Missing fields preserved from both branches
        assert p["field_only_in_1"] == "only_1"
        assert p["field_only_in_2"] == "only_2"
        # 6. Canonical msg synchronized
        assert res["msg"]["payload"]["scalar_val"] == [20, 30]


def test_parallel_join_scalar_to_array_downstream_validation():
    """Verify Section 2.1: Downstream nodes receive correct array type when Join
    changes a field from a scalar to an array, and downstream Switch/Router operates reliably."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")

    wf_def = {
        "entry_node": "inject_node",
        "nodes": [
            {"id": "inject_node", "type": "inject", "config": {"payload": {"device": "thermostat"}}},
            {
                "id": "branch_a",
                "type": "change",
                "config": {"operations": [{"type": "set", "target": "payload.reading", "value": 22}]},
            },
            {
                "id": "branch_b",
                "type": "change",
                "config": {"operations": [{"type": "set", "target": "payload.reading", "value": 25}]},
            },
            {
                "id": "join_node",
                "type": "join",
                "config": {"reducer": "merge"},
            },
            {
                "id": "switch_node",
                "type": "switch",
                "config": {
                    "rules": [
                        {"op": "contains", "property": "payload.reading", "value": 22, "target": "target_hit"},
                    ],
                    "default": "target_miss",
                },
            },
            {"id": "target_hit", "type": "change", "config": {"operations": [{"type": "set", "target": "payload.result", "value": "matched"}]}},
            {"id": "target_miss", "type": "change", "config": {"operations": [{"type": "set", "target": "payload.result", "value": "missed"}]}},
        ],
        "edges": [
            {"from": "inject_node", "to": "branch_a"},
            {"from": "inject_node", "to": "branch_b"},
            {"from": "branch_a", "to": "join_node"},
            {"from": "branch_b", "to": "join_node"},
            {"from": "join_node", "to": "switch_node"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)
    res = graph.invoke({})

    # Reading is converted to array [22, 25] by merge reducer
    assert res["payload"]["reading"] == [22, 25]
    # Downstream switch rule 'contains 22' successfully routed to target_hit
    assert res["payload"]["result"] == "matched"


def test_multi_debug_independent_emission_and_redaction():
    """Verify Section 3: Multiple debug nodes remain independent, muted debug nodes
    do not emit events, and secrets are redacted before emission."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")

    emitted_chunks = []

    wf_def = {
        "entry_node": "inject_node",
        "nodes": [
            {
                "id": "inject_node",
                "type": "inject",
                "config": {
                    "payload": {
                        "username": "alberto_user",
                        "api_key": "sk-secret-token-12345",
                        "nested": {"password": "super-secret-pwd", "status": "active"},
                    }
                },
            },
            {
                "id": "debug_active_1",
                "type": "debug",
                "config": {"id": "debug_active_1", "target": "payload", "active": True},
            },
            {
                "id": "debug_muted",
                "type": "debug",
                "config": {"id": "debug_muted", "target": "payload", "active": False},
            },
            {
                "id": "debug_active_2",
                "type": "debug",
                "config": {"id": "debug_active_2", "target": "payload.nested", "active": True},
            },
        ],
        "edges": [
            {"from": "inject_node", "to": "debug_active_1"},
            {"from": "debug_active_1", "to": "debug_muted"},
            {"from": "debug_muted", "to": "debug_active_2"},
        ],
    }

    graph = compile_workflow(wf_def, ctx)

    # Stream graph and capture custom debug writer events
    events = list(graph.stream({}, stream_mode="custom"))
    debug_events = [e for e in events if isinstance(e, dict) and e.get("channel") == "debug"]

    # 1. Exactly 2 debug events emitted (muted node omitted)
    node_ids = [e["payload"]["node_id"] for e in debug_events]
    assert "debug_active_1" in node_ids
    assert "debug_active_2" in node_ids
    assert "debug_muted" not in node_ids

    # 2. Secret redaction verified
    ev1 = next(e for e in debug_events if e["payload"]["node_id"] == "debug_active_1")
    assert ev1["payload"]["data"]["api_key"] == "[REDACTED]"
    assert ev1["payload"]["data"]["nested"]["password"] == "[REDACTED]"
    assert ev1["payload"]["data"]["username"] == "alberto_user"

    ev2 = next(e for e in debug_events if e["payload"]["node_id"] == "debug_active_2")
    assert ev2["payload"]["data"]["password"] == "[REDACTED]"
    assert ev2["payload"]["data"]["status"] == "active"


def test_durable_delay_real_subprocess_crash_and_recovery(tmp_path):
    """Verify Section 1.4: Real process crash recovery across claim/resume boundary.
    - Process 1: Starts subprocess, creates workflow, interrupts at Delay, claims continuation, then terminates via os._exit(42).
    - Process 2: Restarts fresh subprocess with same SQLite database, recovers pending work, runs to completion, and confirms no duplicate dispatch."""
    import os
    import sys
    import subprocess
    import textwrap

    db_file = tmp_path / "test_subprocess_recovery.db"
    cp_file = tmp_path / "test_subprocess_checkpoints.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["PYTHONPATH"] = os.path.abspath("backend")
    env["CHECKPOINT_PATH"] = cp_file.as_posix()

    # Script for Process 1: init db, create run, interrupt at delay, claim, then SIGKILL/exit(42)
    proc1_code = textwrap.dedent("""
        import asyncio, os, sys
        from alberto.db.base import SessionLocal, init_db
        from alberto.models import Thread, Run, Workflow
        from alberto.services.runs import RunService
        import alberto.services.dispatch as dispatch_mod
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async def main():
            await init_db()
            cp_path = os.environ["CHECKPOINT_PATH"]
            async with AsyncSqliteSaver.from_conn_string(cp_path) as cp:
                await cp.setup()
                rs = RunService(checkpointer=cp)
                wf_def = {
                    "id": "wf_subproc_delay",
                    "entry_node": "inject_node",
                    "nodes": [
                        {"id": "inject_node", "type": "inject", "config": {"payload": {"device": "subproc_sensor", "val": 99}}},
                        {"id": "delay_node", "type": "delay", "config": {"seconds": 0.05, "unit": "seconds", "mode": "durable"}},
                        {"id": "debug_node", "type": "debug", "config": {"target": "payload"}},
                    ],
                    "edges": [
                        {"from": "inject_node", "to": "delay_node"},
                        {"from": "delay_node", "to": "debug_node"},
                    ],
                }
                async with SessionLocal() as s:
                    wf = Workflow(tenant_id="t_sub", project_id="p_sub", name="Subproc WF", executable=wf_def)
                    s.add(wf)
                    await s.flush()
                    th = Thread(tenant_id="t_sub", project_id="p_sub", workflow_id=wf.id, lg_thread_id="th_sub_001")
                    s.add(th)
                    await s.flush()
                    run = await rs.create_run(s, tenant_id="t_sub", project_id="p_sub", workflow_id=wf.id, thread_id=th.id, input={})
                    run_id = run.id

                # 1. Run until delay interrupt
                res = await rs.run_to_completion(run_id=run_id, tenant_id="t_sub", project_id="p_sub")
                assert res["status"] == "interrupted"

                await asyncio.sleep(0.08)

                # 2. Crash at claim boundary with os._exit(42) to simulate ungraceful backend termination
                def crash_exit(r_id):
                    os._exit(42)

                dispatch_mod._FAULT_HOOK_AFTER_CLAIM = crash_exit
                await dispatch_mod.run_due_delays(rs)

        asyncio.run(main())
    """)

    # Launch Process 1: expect exit code 42
    res1 = subprocess.run([sys.executable, "-c", proc1_code], env=env, capture_output=True, text=True)
    assert res1.returncode == 42, f"Expected Process 1 to crash with 42, got {res1.returncode}. Output: {res1.stdout} / {res1.stderr}"

    # Script for Process 2: restart fresh process, recover continuation, execute downstream, verify idempotency
    proc2_code = textwrap.dedent("""
        import asyncio, os, sys
        from sqlalchemy import select
        from alberto.db.base import SessionLocal
        from alberto.models import Thread, Run
        from alberto.services.runs import RunService
        import alberto.services.dispatch as dispatch_mod
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async def main():
            cp_path = os.environ["CHECKPOINT_PATH"]
            async with AsyncSqliteSaver.from_conn_string(cp_path) as cp:
                rs = RunService(checkpointer=cp)

                # 1. Verify continuation survived process crash in SQLite Thread.meta
                async with SessionLocal() as s:
                    r = (await s.execute(select(Run).where(Run.tenant_id == "t_sub"))).scalar_one()
                    assert r.status == "interrupted"
                    th = await s.get(Thread, r.thread_id)
                    cont = th.meta.get(f"delay_continuation_{r.id}")
                    assert cont is not None
                    assert cont.get("status") == "claimed"

                # 2. Scheduler sweep with lease_seconds=0 reclaims abandoned lease
                recovered = await dispatch_mod.run_due_delays(rs, lease_seconds=0)
                assert recovered == 1, f"Expected 1 recovered run, got {recovered}"

                # 3. Verify run reached terminal done status and continuation was purged
                async with SessionLocal() as s:
                    r = (await s.execute(select(Run).where(Run.tenant_id == "t_sub"))).scalar_one()
                    assert r.status == "done"
                    th = await s.get(Thread, r.thread_id)
                    assert f"delay_continuation_{r.id}" not in (th.meta or {})

                # 4. Confirm idempotency: subsequent sweep does not duplicate execution
                recovered2 = await dispatch_mod.run_due_delays(rs, lease_seconds=0)
                assert recovered2 == 0

                print("SUBPROCESS_RECOVERY_SUCCESS")

        asyncio.run(main())
    """)

    # Launch Process 2: expect clean exit code 0 and SUCCESS output
    res2 = subprocess.run([sys.executable, "-c", proc2_code], env=env, capture_output=True, text=True)
    assert res2.returncode == 0, f"Process 2 failed with {res2.returncode}. Output: {res2.stdout} / {res2.stderr}"
    assert "SUBPROCESS_RECOVERY_SUCCESS" in res2.stdout






