"""Workflow endpoints (CRUD + validate)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.deps import CurrentUser, current_tenant_id, get_session, require_role
from alberto.schemas.dto import (
    CanvasSaveIn,
    ExecutableIn,
    ExportIn,
    ImportIn,
    ImportReport,
    StepExecutionIn,
    StepExecutionOut,
    ValidateOut,
    WorkflowCreate,
    WorkflowOut,
    WorkflowUpdate,
)
from alberto.services.portability import PortabilityService
from alberto.services.triggers import default_scope_for
from alberto.services.versions import safe_snapshot
from alberto.services.workflows import WorkflowService

router = APIRouter(prefix="/v1/projects/{project_id}/workflows", tags=["workflows"])


@router.post("/export")
async def export_workflows(project_id: str, body: ExportIn, session: AsyncSession = Depends(get_session),
                           tenant_id: str = Depends(current_tenant_id)):
    """Serialize the selected workflows (canvas + executable) into a downloadable bundle."""
    return await PortabilityService.export(session, tenant_id, project_id, "workflow", body.ids)


@router.post("/import", response_model=ImportReport)
async def import_workflows(project_id: str, body: ImportIn, session: AsyncSession = Depends(get_session),
                           tenant_id: str = Depends(current_tenant_id), user: CurrentUser = Depends(require_role("editor"))):
    """Create workflows from an uploaded bundle in THIS project (imported as drafts)."""
    if body.type not in (None, "workflow"):
        raise HTTPException(422, f"This file contains '{body.type}' exports — import it from the matching screen.")
    try:
        return await PortabilityService.import_bundle(session, tenant_id, project_id, body.model_dump(), author=user)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
):
    return await WorkflowService.list(session, tenant_id, project_id)


@router.post("", response_model=WorkflowOut, status_code=201)
async def create_workflow(
    project_id: str,
    body: WorkflowCreate,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    wf = await WorkflowService.create(
        session, tenant_id, project_id,
        name=body.name, description=body.description,
        executable=body.executable, canvas=body.canvas,
    )
    await safe_snapshot(session, "workflow", wf, author=user)
    return wf


@router.post("/validate", response_model=ValidateOut)
async def validate_executable(project_id: str, body: ExecutableIn):
    result = WorkflowService.validate(body.executable)
    return ValidateOut(valid=result.valid, errors=result.errors, warnings=result.warnings)


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    project_id: str,
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
):
    wf = await WorkflowService.get(session, tenant_id, workflow_id)
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    return wf


@router.patch("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    project_id: str,
    workflow_id: str,
    body: WorkflowUpdate,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    wf = await WorkflowService.get(session, tenant_id, workflow_id)
    if wf is None or wf.project_id != project_id:
        raise HTTPException(404, "Workflow not found")
    name = body.name.strip() if body.name is not None else None
    if body.name is not None and not name:
        raise HTTPException(422, "Workflow name is required")
    wf = await WorkflowService.update(session, wf, name=name, description=body.description)
    await safe_snapshot(session, "workflow", wf, author=user)
    return wf


@router.put("/{workflow_id}/executable", response_model=ValidateOut)
async def update_executable(
    project_id: str,
    workflow_id: str,
    body: ExecutableIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    wf = await WorkflowService.get(session, tenant_id, workflow_id)
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    result = await WorkflowService.update_executable(
        session, wf, body.executable, require_valid=True,
        owner=str(user.id), scope=default_scope_for(user.role),
    )
    if result.valid:
        await safe_snapshot(session, "workflow", wf, author=user)
    return ValidateOut(valid=result.valid, errors=result.errors, warnings=result.warnings)


@router.post("/{workflow_id}/publish", response_model=WorkflowOut)
async def publish_workflow(
    project_id: str,
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Validate the stored executable and mark the workflow active (a published version)."""
    wf = await WorkflowService.get(session, tenant_id, workflow_id)
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    result = WorkflowService.validate(wf.executable or {})
    if not result.valid:
        raise HTTPException(422, detail={"errors": result.errors})
    # Governance: reject publishing a workflow that uses a chat model the project's
    # allowed_models forbids. Admission (services/budget.enforce_project_budget) validates the
    # run's model at runtime; this catches EVERY per-node model before the workflow goes live.
    # No-op unless the project configures an allow-list.
    from sqlalchemy import select

    from alberto.models import Project
    from alberto.services.budget import disallowed_workflow_models

    proj = (await session.execute(
        select(Project).where(Project.tenant_id == tenant_id, Project.id == project_id)
    )).scalar_one_or_none()
    bad = disallowed_workflow_models(proj.config if proj else None, wf.executable or {})
    if bad:
        raise HTTPException(422, detail={"errors": [
            f"model {m!r} is not in this project's allowed_models" for m in bad
        ]})
    wf.status = "active"
    wf.active_version = (wf.active_version or 1) + 1
    await session.commit()
    await session.refresh(wf)
    # (Re)register webhook/schedule/etc. The publisher becomes the identity an unattended run
    # acts as, and (for a NEW trigger) whether it is the team's or their own - unless the
    # trigger already has those, which an edit never overwrites.
    await WorkflowService._sync_triggers(
        session, wf, owner=str(user.id), scope=default_scope_for(user.role),
    )
    await safe_snapshot(session, "workflow", wf, author=user)
    return wf


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    project_id: str,
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("editor")),
):
    wf = await WorkflowService.get(session, tenant_id, workflow_id)
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    await WorkflowService.delete(session, wf)


@router.put("/{workflow_id}/canvas", response_model=ValidateOut)
async def save_canvas(
    project_id: str,
    workflow_id: str,
    body: CanvasSaveIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    wf = await WorkflowService.get(session, tenant_id, workflow_id)
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    result = await WorkflowService.save_canvas(
        session, wf, body.canvas, body.executable,
        owner=str(user.id), scope=default_scope_for(user.role),
    )
    await safe_snapshot(session, "workflow", wf, author=user)
    return ValidateOut(valid=result.valid, errors=result.errors, warnings=result.warnings)


@router.post("/{workflow_id}/step", response_model=StepExecutionOut)
async def execute_step(
    project_id: str,
    workflow_id: str,
    body: StepExecutionIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Execute a single workflow node with mock or upstream input state for interactive testing.

    Enforces:
    - Node must belong to the saved workflow
    - Default mode is dry_run (safe simulation without mutating external side effects)
    - Untrusted caller approval flags are purged
    - Tool execution policy enforcement is strictly preserved
    """
    import inspect
    import json
    import time

    from alberto.engine.registry import get_spec
    from alberto.services.runtime import build_compile_context

    wf = await WorkflowService.get(session, tenant_id, workflow_id)
    if wf is None or wf.project_id != project_id:
        raise HTTPException(404, "Workflow not found")

    # Stale/concurrent modification protection
    if getattr(body, "active_version", None) is not None and wf.active_version is not None:
        if body.active_version != wf.active_version:
            raise HTTPException(409, f"Workflow has been modified (version {wf.active_version} != {body.active_version}). Reload required.")

    # Verify node identity against workflow
    wf_exec_nodes = (wf.executable or {}).get("nodes", [])
    wf_canvas_nodes = (wf.canvas or {}).get("nodes", [])

    saved_node = None
    for n in wf_exec_nodes:
        if isinstance(n, dict) and n.get("id") == body.node_id:
            saved_node = {"type": n.get("type"), "config": n.get("config") or {}}
            break
    if not saved_node:
        for n in wf_canvas_nodes:
            if isinstance(n, dict) and n.get("id") == body.node_id:
                data = n.get("data") or {}
                saved_node = {
                    "type": data.get("nodeType") or n.get("type"),
                    "config": data.get("config") or n.get("config") or {},
                }
                break

    if not saved_node and (wf_exec_nodes or wf_canvas_nodes):
        raise HTTPException(422, f"Node '{body.node_id}' does not belong to workflow '{workflow_id}'")

    if saved_node:
        if body.node_type != saved_node["type"]:
            raise HTTPException(
                422,
                f"Node type spoofing detected: node '{body.node_id}' is saved as '{saved_node['type']}', got '{body.node_type}'",
            )
        saved_cfg = dict(saved_node.get("config") or {})
        req_cfg = dict(body.config or {})

        # Tool node tampering check
        if body.node_type == "tool_call":
            saved_tool_id = saved_cfg.get("tool_id")
            req_tool_id = req_cfg.get("tool_id")
            if saved_tool_id and req_tool_id != saved_tool_id:
                raise HTTPException(
                    422,
                    f"Tool tampering detected: node '{body.node_id}' is configured with tool '{saved_tool_id}', got '{req_tool_id}'",
                )
            if saved_cfg.get("auth_provider_id") and req_cfg.get("auth_provider_id") != saved_cfg.get("auth_provider_id"):
                raise HTTPException(422, f"Credential reference tampering detected on node '{body.node_id}'")

        # Agent node tampering check
        elif body.node_type in ("agent", "deep_agent"):
            saved_agent_id = saved_cfg.get("agent_id")
            req_agent_id = req_cfg.get("agent_id")
            if saved_agent_id and req_agent_id != saved_agent_id:
                raise HTTPException(
                    422,
                    f"Agent tampering detected: node '{body.node_id}' is configured with agent '{saved_agent_id}', got '{req_agent_id}'",
                )
            saved_tools = set(saved_cfg.get("tools") or [])
            req_tools = set(req_cfg.get("tools") or [])
            if not req_tools.issubset(saved_tools):
                raise HTTPException(422, f"Unauthorized tool injection on agent node '{body.node_id}': {req_tools - saved_tools}")

            saved_toolsets = set(saved_cfg.get("toolsets") or [])
            req_toolsets = set(req_cfg.get("toolsets") or [])
            if not req_toolsets.issubset(saved_toolsets):
                raise HTTPException(422, f"Unauthorized toolset injection on agent node '{body.node_id}': {req_toolsets - saved_toolsets}")

            saved_mcp = set(saved_cfg.get("mcp_servers") or [])
            req_mcp = set(req_cfg.get("mcp_servers") or [])
            if not req_mcp.issubset(saved_mcp):
                raise HTTPException(422, f"Unauthorized MCP server injection on agent node '{body.node_id}': {req_mcp - saved_mcp}")

        # Subworkflow node tampering check
        elif body.node_type == "subworkflow":
            saved_subwf = saved_cfg.get("subworkflow_id")
            req_subwf = req_cfg.get("subworkflow_id")
            if saved_subwf and req_subwf != saved_subwf:
                raise HTTPException(
                    422,
                    f"Subworkflow tampering detected: node '{body.node_id}' is configured with subworkflow '{saved_subwf}', got '{req_subwf}'",
                )

        # Webhook out tampering check
        elif body.node_type == "webhook_out":
            if saved_cfg.get("auth_provider_id") and req_cfg.get("auth_provider_id") != saved_cfg.get("auth_provider_id"):
                raise HTTPException(422, f"Credential reference tampering detected on node '{body.node_id}'")
            req_url = req_cfg.get("url") or ""
            if req_url:
                from alberto.util.ssrf import validate_url
                try:
                    res_val = validate_url(req_url)
                    if inspect.isawaitable(res_val):
                        await res_val
                except Exception as e:
                    raise HTTPException(422, f"Unauthorized destination URL: {e}") from e

    try:
        spec = get_spec(body.node_type)
    except KeyError as e:
        raise HTTPException(422, str(e)) from e

    wf_def = wf.executable or {"nodes": wf_canvas_nodes}
    ctx = await build_compile_context(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        workflow_id=workflow_id,
        workflow_def=wf_def,
    )
    is_dry_run = body.mode != "live"
    ctx.dry_run = is_dry_run

    # Sanitize untrusted input state and config: purge caller-spoofed approval/permission flags
    for k in ("approved", "human_approved", "requires_approval", "entitlements", "roles", "is_admin", "super_user", "admin"):
        body.config.pop(k, None)
        if body.input_state:
            body.input_state.pop(k, None)

    node_fn = spec.factory(body.config, ctx)

    state = dict(body.input_state or {})

    if "msg" not in state:
        state["msg"] = {"payload": state.get("payload", {}), "topic": state.get("topic", "")}

    t0 = time.perf_counter()
    try:
        if inspect.iscoroutinefunction(node_fn):
            out = await node_fn(state)
        elif callable(node_fn):
            res = node_fn(state)
            out = await res if inspect.isawaitable(res) else res
        elif hasattr(node_fn, "ainvoke"):
            out = await node_fn.ainvoke(state)
        elif hasattr(node_fn, "invoke"):
            out = node_fn.invoke(state)
        else:
            raise TypeError(f"Node factory {node_fn!r} is not callable")

        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        clean_out = json.loads(json.dumps(out, default=str)) if isinstance(out, dict) else {"result": str(out)}

        # Check for policy violation or mock flags across top-level and nested envelopes
        mocked = False
        requires_appr = False
        err_msg = None
        unsupported_dry_run = False

        def _scan_flags(d: dict):
            nonlocal mocked, requires_appr, err_msg, unsupported_dry_run
            if d.get("mocked") or d.get("simulated"):
                mocked = True
            if d.get("requires_approval"):
                requires_appr = True
            if d.get("unsupported_dry_run"):
                unsupported_dry_run = True
            if d.get("error") and not err_msg:
                err_str = str(d.get("error"))
                if "policy violation" in err_str.lower() or unsupported_dry_run or requires_appr:
                    err_msg = err_str

        if isinstance(clean_out, dict):
            _scan_flags(clean_out)
            for v in clean_out.values():
                if isinstance(v, dict):
                    _scan_flags(v)
                    for sub_v in v.values():
                        if isinstance(sub_v, dict):
                            _scan_flags(sub_v)

        ok = err_msg is None and not requires_appr and not unsupported_dry_run
        return StepExecutionOut(
            ok=ok,
            output=clean_out,
            duration_ms=duration_ms,
            error=err_msg,
            mocked=mocked,
            requires_approval=requires_appr,
            unsupported_dry_run=unsupported_dry_run,
        )
    except Exception as e:
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        return StepExecutionOut(ok=False, output={}, error=str(e), duration_ms=duration_ms)
