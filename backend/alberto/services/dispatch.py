"""DispatchService - turn an inbound trigger event into a run and execute it.

Shared by the webhook route, the scheduler, the email poller, and chat channels.
"""

from __future__ import annotations

from typing import Any

import inspect
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from alberto.db.base import SessionLocal
from alberto.models import Thread, Trigger
from alberto.services.runs import RunService
from alberto.services.triggers import TriggerService

log = logging.getLogger("forge.dispatch")


def _channel_thread_key(conversation_key: str) -> str:
    return f"ch:{conversation_key}"


# Canonical run source per trigger kind, for the Traces conversation view.
_TRIGGER_SOURCE = {
    "webhook_in": "webhook", "schedule": "schedule",
    "email_in": "channel_email", "app_event": "app_event",
}


async def _find_channel_thread(s, tenant_id: str, workflow_id: str, conversation_key: str) -> str | None:
    """Find the persisted Thread for a channel conversation so multi-turn email
    conversations keep history through the checkpointer (audit F6)."""
    row = (await s.execute(
        select(Thread).where(
            Thread.tenant_id == tenant_id,
            Thread.workflow_id == workflow_id,
            Thread.user_external_id == _channel_thread_key(conversation_key),
        ).order_by(Thread.updated_at.desc())
    )).scalars().first()
    return row.id if row else None


async def dispatch_trigger(run_service: RunService, trigger: Trigger, payload, *, stamp: bool = True) -> dict:
    """Create a run for `trigger` from `payload` and run it to completion.

    `stamp` controls whether last_fired_at is written here. The scheduler already claims a
    schedule (re-check + stamp in one txn) before calling this, so it passes stamp=False to
    avoid a redundant second write; the webhook/inbound paths keep the default True."""
    run_input = TriggerService.build_input(trigger, payload)
    # Whose accounts this unattended run acts as. A webhook or a schedule has nobody signed in,
    # so without an identity here every per-user connector (which is every catalog connector)
    # would fail at its first tool call with "the acting user has not connected their credential".
    # The trigger carries the editor who set it up, so a scheduled workflow reads THEIR mailbox -
    # the same account they connected when building it.
    end_user = {"id": trigger.run_as_user_id} if trigger.run_as_user_id else None
    async with SessionLocal() as s:
        run = await run_service.create_run(
            s, tenant_id=trigger.tenant_id, project_id=trigger.project_id,
            workflow_id=trigger.workflow_id, input=run_input, end_user=end_user,
            source=_TRIGGER_SOURCE.get(trigger.kind, trigger.kind or "webhook"),
        )
        run_id = run.id
        # stamp last_fired_at on the trigger (unless the caller already claimed it)
        if stamp:
            t = await s.get(Trigger, trigger.id)
            if t is not None:
                t.last_fired_at = datetime.utcnow()
                if (t.config or {}).get("run_at"):
                    t.enabled = False
                await s.commit()
    # Offload to the worker queue when configured (webhook/schedule need no synchronous
    # reply); otherwise run inline. Either way per-tenant concurrency is bounded (audit P1).
    from alberto.queue import enqueue_run
    if await enqueue_run(run_id, trigger.tenant_id, trigger.project_id):
        return {"run_id": run_id, "status": "queued", "queued": True}
    return await run_service.run_to_completion(
        run_id=run_id, tenant_id=trigger.tenant_id, project_id=trigger.project_id,
    )


async def dispatch_message(
    run_service: RunService, *, tenant_id: str, project_id: str, workflow_id: str,
    text: str, thread_id: str | None = None, conversation_key: str | None = None,
    source: str = "channel", end_user: dict | None = None, run_context: dict | None = None,
) -> dict:
    """Run `workflow_id` with a single user `text` (used by email channels).

    `conversation_key` (the provider's stable conversation id) maps the inbound message to
    a persisted Thread so a multi-turn conversation keeps its history via the checkpointer
    (audit F6) - otherwise every message would start a fresh, context-free thread.

    `end_user` binds the run's on-behalf-of identity (so a per-user auth provider resolves that
    user's connected credential) and `run_context` forwards ephemeral per-run values (an inline
    token / session, exposed to tools as {{ctx.*}}) - the same on-behalf-of channels the run API
    uses, so eval/channel runs authenticate like a Playground run."""
    run_input = {"messages": [{"role": "user", "content": text or ""}]}
    if thread_id is None and conversation_key:
        async with SessionLocal() as s:
            thread_id = await _find_channel_thread(s, tenant_id, workflow_id, conversation_key)
    new_thread = thread_id is None
    async with SessionLocal() as s:
        run = await run_service.create_run(
            s, tenant_id=tenant_id, project_id=project_id, workflow_id=workflow_id,
            input=run_input, thread_id=thread_id, source=source, end_user=end_user,
        )
        run_id, run_thread_id = run.id, run.thread_id
        # Tag a freshly-created thread with the conversation key so the next inbound message
        # on the same conversation continues it.
        if conversation_key and new_thread:
            th = await s.get(Thread, run_thread_id)
            if th is not None and not th.user_external_id:
                th.user_external_id = _channel_thread_key(conversation_key)
                await s.commit()
    result = await run_service.run_to_completion(
        run_id=run_id, tenant_id=tenant_id, project_id=project_id, run_context=run_context)
    result["thread_id"] = run_thread_id
    result["workflow_id"] = workflow_id
    return result


async def run_due_schedules(run_service: RunService) -> int:
    """Fire every schedule trigger that is due. Returns how many fired.

    Each due trigger is CLAIMED atomically before running - re-fetch, re-check due, and stamp
    last_fired_at in one transaction - so a second scheduler tick or replica that also saw it
    due finds it already claimed and skips it (no duplicate scheduled runs).
    For one-time triggers (run_at), the Run record is created in the SAME transaction as the
    claim, guaranteeing crash-safe durability without losing execution on restart.
    """
    async with SessionLocal() as s:
        due = await TriggerService.due_schedule_triggers(s)
    fired = 0
    for trig in due:
        run_id = None
        is_one_time = False
        async with SessionLocal() as s:
            t = await s.get(Trigger, trig.id)
            if t is None or not TriggerService.is_due(t):
                continue  # already claimed by a concurrent tick / no longer due
            t.last_fired_at = datetime.utcnow()
            is_one_time = bool((t.config or {}).get("run_at"))
            if is_one_time:
                # Atomically claim trigger and create durable Run record in SQLite
                run_input = TriggerService.build_input(t, None)
                end_user = {"id": t.run_as_user_id} if t.run_as_user_id else None
                run = await run_service.create_run(
                    s,
                    tenant_id=t.tenant_id,
                    project_id=t.project_id,
                    workflow_id=t.workflow_id,
                    input=run_input,
                    end_user=end_user,
                    source="schedule",
                )
                run_id = run.id
                t.enabled = False
                t.meta = {
                    **(t.meta or {}),
                    "one_time_run_id": run_id,
                    "dispatch_status": "dispatched",
                    "dispatched_at": datetime.utcnow().isoformat(),
                }
            await s.commit()

        try:
            if is_one_time and run_id:
                from alberto.queue import enqueue_run
                if not await enqueue_run(run_id, trig.tenant_id, trig.project_id):
                    await run_service.run_to_completion(
                        run_id=run_id, tenant_id=trig.tenant_id, project_id=trig.project_id,
                    )
            else:
                await dispatch_trigger(run_service, trig, None, stamp=False)
            fired += 1
        except Exception:  # noqa: BLE001 - one bad schedule must not stop the rest
            log.exception("schedule trigger %s failed", trig.id)
    return fired



async def run_due_app_events(run_service: RunService) -> int:
    """Poll every due app_event trigger; dispatch a run per NEW item. Returns total fired."""
    from sqlalchemy import select

    from alberto.models import Trigger

    async with SessionLocal() as s:
        rows = list((await s.execute(
            select(Trigger).where(Trigger.kind == "app_event", Trigger.enabled.is_(True))
        )).scalars())
    fired = 0
    for trig in rows:
        if not TriggerService.is_due(trig):
            continue
        try:
            fired += await _poll_app_event(run_service, trig)
        except Exception:  # noqa: BLE001 - one bad source must not stop the rest
            log.exception("app_event trigger %s failed", trig.id)
    return fired


async def _poll_app_event(run_service: RunService, trig) -> int:
    import json

    import jmespath

    from alberto.util.http import shared_async_client
    from alberto.util.ssrf import guarded_request

    cfg = trig.config or {}
    url = cfg.get("poll_url")
    if not url:
        return 0

    # Claim this tick atomically BEFORE doing any work: re-check due + stamp last_fired_at
    # in one transaction so an overlapping scheduler tick can't re-enter and double-dispatch
    # the same items (audit F9). Read the seen-set under the same read.
    async with SessionLocal() as s:
        t = await s.get(Trigger, trig.id)
        if t is None or not TriggerService.is_due(t):
            return 0  # already claimed by another tick / no longer due
        first_poll = t.last_fired_at is None
        seen = set((t.meta or {}).get("seen", []))
        t.last_fired_at = datetime.utcnow()
        await s.commit()

    method = (cfg.get("method") or "GET").upper()
    # Follow redirects through the SSRF guard, which re-validates EVERY hop; httpx's own
    # follow_redirects would connect to a redirect target (e.g. 169.254.169.254) unchecked (H2).
    r = await guarded_request(shared_async_client(), method, url, timeout=20, follow_redirects=True)
    r.raise_for_status()
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        data = r.text

    items = jmespath.search(cfg["items_path"], data) if cfg.get("items_path") else data
    if items is None:
        items = []
    if not isinstance(items, list):
        items = [items]

    dedupe = cfg.get("dedupe_key")

    def _key(item) -> str:
        if dedupe:
            return str(jmespath.search(dedupe, item))
        return json.dumps(item, sort_keys=True, default=str)

    new_items = []
    new_keys: list[str] = []
    for item in items:
        k = _key(item)
        if k in seen:
            continue
        seen.add(k)
        new_keys.append(k)
        new_items.append(item)

    # Persist the updated seen-set, merging with any concurrent writer's keys (read-modify-
    # write under a fresh read) so a lost update can't resurrect already-dispatched items.
    if new_keys:
        async with SessionLocal() as s:
            t = await s.get(Trigger, trig.id)
            if t is not None:
                # Keep `seen` as an ORDERED list (oldest -> newest) so capping to the most-recent
                # 1000 retains recent keys. The prior code stored a set and sliced list(set)[-1000:],
                # whose arbitrary order could evict just-seen keys and re-fire already-dispatched
                # items once the cap was exceeded.
                seen_list = list((t.meta or {}).get("seen", []))
                have = set(seen_list)
                for k in new_keys:
                    if k not in have:
                        seen_list.append(k)
                        have.add(k)
                t.meta = {**(t.meta or {}), "seen": seen_list[-1000:]}
                await s.commit()

    count = 0
    # First poll only baselines the seen-set (don't replay history).
    if not first_poll:
        for item in new_items:
            text = jmespath.search(cfg["message_path"], item) if cfg.get("message_path") else item
            text = text if isinstance(text, str) else json.dumps(text, default=str)
            await dispatch_message(
                run_service, tenant_id=trig.tenant_id, project_id=trig.project_id,
                workflow_id=trig.workflow_id, text=str(text),
            )
            count += 1
    return count


async def run_due_source_syncs() -> int:
    """Run due MCP source synchronization jobs across projects.
    Executes configured sync workflows using existing scheduler loop."""
    from alberto.services.source_sync import SourceSyncCoordinator

    async with SessionLocal() as s:
        results = await SourceSyncCoordinator.execute_due_sync_jobs(s)
    return len([r for r in results if r.get("ok")])


_FAULT_HOOK_AFTER_CLAIM: Any = None


async def run_due_delays(run_service: RunService, lease_seconds: int = 30) -> int:
    """Resume runs paused at a durable Delay node whose deadline has passed.
    
    Crash-Safe Guarantee:
    - Atomically claims the continuation with a renewable lease (status="claimed", claimed_at).
    - Preserves continuation metadata in Thread.meta across worker crashes.
    - If a crash occurs before or during resume, subsequent scheduler sweeps reclaim expired leases.
    - Purged permanently only upon terminal run completion in RunService._finalize.
    """
    from alberto.models import Run, Thread
    now = datetime.now(timezone.utc)
    resumed_count = 0
    async with SessionLocal() as session:
        runs = list((await session.execute(
            select(Run).where(Run.status == "interrupted")
        )).scalars())

    for r_entry in runs:
        claimed = False
        async with SessionLocal() as session:
            th = await session.get(Thread, r_entry.thread_id)
            if not th or not th.meta:
                continue
            delay_key = f"delay_continuation_{r_entry.id}"
            delay_info = (th.meta or {}).get(delay_key)
            if not delay_info or not isinstance(delay_info, dict):
                continue
            deadline_str = delay_info.get("deadline")
            if not deadline_str:
                continue
            try:
                deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
                if deadline.tzinfo is not None:
                    now_tz = datetime.now(deadline.tzinfo)
                    is_due = deadline <= now_tz
                else:
                    is_due = deadline <= datetime.now(timezone.utc).replace(tzinfo=None)
            except Exception:
                continue

            if not is_due:
                continue

            # Check if already claimed and lease is still active
            status = delay_info.get("status")
            claimed_at_str = delay_info.get("claimed_at")
            if status == "claimed" and claimed_at_str:
                try:
                    claimed_at = datetime.fromisoformat(claimed_at_str.replace("Z", "+00:00"))
                    if claimed_at.tzinfo is not None:
                        now_tz = datetime.now(claimed_at.tzinfo)
                        lease_active = (now_tz - claimed_at).total_seconds() < lease_seconds
                    else:
                        lease_active = (datetime.now(timezone.utc).replace(tzinfo=None) - claimed_at).total_seconds() < lease_seconds
                    if lease_active:
                        continue
                except Exception:
                    pass

            r = await session.get(Run, r_entry.id)
            if not r or r.status != "interrupted":
                continue

            # Atomically claim with lease WITHOUT removing continuation from Thread.meta!
            th_meta = dict(th.meta)
            updated_info = dict(delay_info)
            updated_info["status"] = "claimed"
            updated_info["claimed_at"] = now.isoformat()
            th_meta[delay_key] = updated_info
            th.meta = th_meta
            await session.commit()
            claimed = True

        if not claimed:
            continue

        # Optional test fault-injection hook
        if _FAULT_HOOK_AFTER_CLAIM is not None:
            if inspect.iscoroutinefunction(_FAULT_HOOK_AFTER_CLAIM):
                await _FAULT_HOOK_AFTER_CLAIM(r_entry.id)
            else:
                _FAULT_HOOK_AFTER_CLAIM(r_entry.id)

        try:
            await run_service.resume(
                run_id=r_entry.id,
                tenant_id=r_entry.tenant_id,
                project_id=r_entry.project_id,
                value={"delayed": True},
            )
            resumed_count += 1
        except Exception:
            log.exception("Failed to resume delayed run %s", r_entry.id)

    return resumed_count
