import asyncio
import pytest
from alberto.services.runs import _RunBroker, run_streams, RunService
from alberto.models import Run, Thread, Trace, Workflow
from alberto.db.base import SessionLocal
from datetime import datetime


@pytest.mark.asyncio
async def test_run_broker_bounded_buffer():
    broker = _RunBroker(maxlen=5)

    for i in range(1, 11):
        await broker.publish({"event": "message", "data": {"seq": i}})

    assert len(broker.events) == 5
    retained_seqs = [item[0] for item in broker.events]
    assert retained_seqs == [6, 7, 8, 9, 10]

    assert broker.has_evicted(1) is True
    assert broker.has_evicted(5) is True
    assert broker.has_evicted(6) is False
    assert broker.has_evicted(10) is False
    assert broker.has_evicted(0) is False


@pytest.mark.asyncio
async def test_run_broker_slow_subscriber_bounded_queue():
    """Slow subscriber queue must be bounded and overflow must drop subscriber without blocking publisher."""
    broker = _RunBroker(maxlen=5)
    broker.sub_queue_size = 3  # small bound for test

    sub_iter = broker.subscribe(last_event_id=0)
    # Start subscription by advancing into generator
    task = asyncio.create_task(sub_iter.__anext__())
    await asyncio.sleep(0.01)

    # Publish more events than subscriber queue can hold
    for i in range(1, 10):
        await broker.publish({"event": "msg", "data": i})

    # The publisher did not block and successfully finished
    await broker.finish()

    # The initial item should be yielded
    item = await task
    assert item[0] == 1


@pytest.mark.asyncio
async def test_stream_active_run_reconnect_eviction_gap():
    """Client reconnecting to an active run requesting an evicted ID receives an explicit gap event."""
    run_service = RunService()
    tenant_id = "tenant-gap-test"
    project_id = "proj-gap-test"
    run_id = "run-gap-1"

    async with SessionLocal() as session:
        wf = Workflow(tenant_id=tenant_id, project_id=project_id, name="wf-gap", executable={"nodes": []})
        session.add(wf)
        await session.flush()
        th = Thread(tenant_id=tenant_id, project_id=project_id, workflow_id=wf.id, lg_thread_id=f"{tenant_id}:th-gap")
        session.add(th)
        await session.flush()
        run = Run(id=run_id, tenant_id=tenant_id, project_id=project_id, workflow_id=wf.id, thread_id=th.id, status="running")
        session.add(run)
        await session.commit()

    # Set up an active (unfinished) broker with capacity 3
    broker = _RunBroker(maxlen=3)
    async with run_streams._lock:
        run_streams._brokers[run_id] = broker

    # Publish 5 events (seq 1,2 evicted; seq 3,4,5 retained)
    for i in range(1, 6):
        await broker.publish({"event": "message", "data": f"token-{i}"})

    # Client reconnects with last_event_id=1 (evicted)
    stream_gen = run_service.stream(run_id=run_id, tenant_id=tenant_id, project_id=project_id, last_event_id=1)

    # First yielded event must be the explicit 'gap' event
    first_frame = await stream_gen.__anext__()
    assert first_frame["event"] == "gap"
    assert first_frame["data"]["resync"] is True
    assert first_frame["data"]["oldest_retained_id"] == 3
    assert first_frame["data"]["requested_last_event_id"] == 1

    # Following frames must be the retained live frames
    retained_frames = []
    # Publish finish to close stream
    await broker.finish()
    async for frame in stream_gen:
        retained_frames.append(frame)

    assert [f["id"] for f in retained_frames] == ["3", "4", "5"]

    # Cleanup
    async with run_streams._lock:
        run_streams._brokers.pop(run_id, None)


@pytest.mark.asyncio
async def test_stream_completed_run_reconnect_eviction():
    """Client reconnecting to a completed run with evicted broker falls back to DB."""
    run_service = RunService()
    tenant_id = "tenant-gap-done"
    project_id = "proj-gap-done"
    run_id = "run-gap-done-1"

    async with SessionLocal() as session:
        wf = Workflow(tenant_id=tenant_id, project_id=project_id, name="wf-gap", executable={"nodes": []})
        session.add(wf)
        await session.flush()
        th = Thread(tenant_id=tenant_id, project_id=project_id, workflow_id=wf.id, lg_thread_id=f"{tenant_id}:th-done")
        session.add(th)
        await session.flush()
        run = Run(id=run_id, tenant_id=tenant_id, project_id=project_id, workflow_id=wf.id, thread_id=th.id, status="done")
        session.add(run)
        trace = Trace(
            tenant_id=tenant_id, project_id=project_id, workflow_id=wf.id, run_id=run_id, thread_id=th.id,
            name="run", status="done", started_at=datetime.utcnow(), ended_at=datetime.utcnow(),
            ai_response="Final reconstructed answer", source="playground", actor="System",
        )
        session.add(trace)
        await session.commit()

    # Finished broker with evicted items
    broker = _RunBroker(maxlen=3)
    for i in range(1, 6):
        await broker.publish({"event": "message", "data": f"token-{i}"})
    await broker.finish()

    async with run_streams._lock:
        run_streams._brokers[run_id] = broker

    # Reconnect with last_event_id=1 on completed run
    stream_gen = run_service.stream(run_id=run_id, tenant_id=tenant_id, project_id=project_id, last_event_id=1)
    frames = [f async for f in stream_gen]
    assert len(frames) == 1
    assert frames[0]["event"] == "done"
    assert frames[0]["data"]["answer"] == "Final reconstructed answer"

    # Cleanup
    async with run_streams._lock:
        run_streams._brokers.pop(run_id, None)
