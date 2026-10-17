"""Application settings - environment-driven (pydantic-settings).

Local defaults need **no external infra** (SQLite + embedded Chroma + in-process queue).
Every value can be overridden via `.env` or real env vars.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Repo layout: backend/forge/config.py -> parents[2] == repo root. In the container the
# tree is flattened to /app/forge, so parents[2] doesn't exist; fall back to API_ROOT (=/app).
_HERE = Path(__file__).resolve()
API_ROOT = _HERE.parents[1]
REPO_ROOT = _HERE.parents[2] if len(_HERE.parents) > 2 else API_ROOT
_DEFAULT_SCHEMAS_DIR = (
    (API_ROOT / "schemas")
    if (API_ROOT / "schemas").exists()
    else (REPO_ROOT / "packages" / "schemas")
)


def _get_logical_data_root() -> Path:
    env_dir = os.getenv("ALBERTO_DATA_DIR") or os.getenv("FORGE_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    return REPO_ROOT / "data"


def _default_database_url() -> str:
    root = _get_logical_data_root()
    for candidate in [root / "db" / "alberto.db", root / "db" / "forge.db", root / "forge.db"]:
        if candidate.exists():
            return f"sqlite+aiosqlite:///{candidate.as_posix()}"
    db_file = root / "db" / "alberto.db" if (root / "db").exists() else root / "alberto.db"
    return f"sqlite+aiosqlite:///{db_file.as_posix()}"


def _default_checkpoint_db() -> str:
    root = _get_logical_data_root()
    for candidate in [root / "db" / "checkpoints.sqlite", root / "checkpoints.sqlite"]:
        if candidate.exists():
            return candidate.as_posix()
    cp_file = root / "db" / "checkpoints.sqlite" if (root / "db").exists() else root / "checkpoints.sqlite"
    return cp_file.as_posix()


def _default_queue_db() -> str:
    root = _get_logical_data_root()
    for candidate in [root / "db" / "queue.sqlite", root / "queue.sqlite"]:
        if candidate.exists():
            return candidate.as_posix()
    q_file = root / "db" / "queue.sqlite" if (root / "db").exists() else root / "queue.sqlite"
    return q_file.as_posix()


def _default_chroma_path() -> str:
    root = _get_logical_data_root()
    return (root / "chroma").as_posix()


def _default_ladybug_path() -> str:
    root = _get_logical_data_root()
    return (root / "db" / "ladybug").as_posix()


def _default_secret_key_file() -> str:
    root = _get_logical_data_root()
    for candidate in [root / "config" / "master.key", root / "master.key"]:
        if candidate.exists():
            return candidate.as_posix()
    key_file = root / "config" / "master.key" if (root / "config").exists() else root / "master.key"
    return key_file.as_posix()

# Minimum length for a non-empty FORGE_SERVICE_API_TOKEN (enforced by the production guard).
_MIN_SERVICE_TOKEN_LEN = 24


def _as_str_list(v: object) -> list[str]:
    """Parse a list-of-strings setting from env leniently: a JSON array (["a","b"]), a
    comma-separated string (a,b), or blank ("" -> []). Env/compose quoting makes strict-JSON
    list fields brittle - a stray bracket or space (e.g. from a ${VAR:-[]} interpolation)
    otherwise crashes startup - so we normalize here instead of requiring valid JSON."""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    s = str(v).strip()
    if not s:
        return []
    if s.startswith("["):
        import json as _json

        try:
            parsed = _json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed]
        except ValueError:
            pass  # not valid JSON (e.g. unquoted, or a mangled "[") -> strip brackets + split
        s = s.strip("[]")
    return [p.strip().strip('"').strip("'") for p in s.split(",") if p.strip().strip('"').strip("'")]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALBERTO_",
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        env_file = REPO_ROOT / ".env"
        return (
            init_settings,
            EnvSettingsSource(settings_cls, env_prefix="ALBERTO_"),
            EnvSettingsSource(settings_cls, env_prefix="FORGE_"),
            DotEnvSettingsSource(settings_cls, env_file=env_file, env_file_encoding="utf-8", env_prefix="ALBERTO_"),
            DotEnvSettingsSource(settings_cls, env_file=env_file, env_file_encoding="utf-8", env_prefix="FORGE_"),
            file_secret_settings,
        )

    # List-of-strings settings are marked NoDecode (skip pydantic-settings' strict JSON decode)
    # and parsed here so env/compose values may be JSON, comma-separated, or blank - see
    # _as_str_list. Keeps a stray bracket/space from an interpolated default from crashing boot.
    @field_validator(
        "jwt_secret_previous", "cors_origins", "egress_allow_hosts", "egress_deny_hosts",
        "egress_allow_private_hosts", "trusted_proxies", "trusted_hosts",
        "mcp_stdio_allowed_commands", mode="before",
    )
    @classmethod
    def _parse_str_lists(cls, v: object) -> list[str]:
        return _as_str_list(v)

    # tool_vars is a JSON MAP (not a list), so it has its own before-validator: an env var may be
    # unset/blank (-> {}) or a JSON object string. Marked NoDecode so pydantic-settings does not
    # crash on a blank value before we get here; a malformed JSON object still fails loudly.
    @field_validator("tool_vars", mode="before")
    @classmethod
    def _parse_tool_vars(cls, v: object) -> dict[str, str]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
        s = str(v).strip()
        if not s:
            return {}
        import json as _json

        parsed = _json.loads(s)
        if not isinstance(parsed, dict):
            raise ValueError('FORGE_TOOL_VARS must be a JSON object, e.g. {"api_base":"https://..."}')
        return {str(k): str(val) for k, val in parsed.items()}

    @field_validator("connector_oauth_apps", mode="before")
    @classmethod
    def _parse_connector_oauth_apps(cls, v: object) -> dict[str, dict]:
        """{"google": {"client_id": "...", "client_secret": "..."}} - one entry per credential
        group. Fails loudly on a malformed value: a silently-empty map would send every user
        back to pasting credentials with no indication why."""
        if v is None:
            return {}
        if isinstance(v, dict):
            return {str(k): dict(val) for k, val in v.items() if isinstance(val, dict)}
        s = str(v).strip()
        if not s:
            return {}
        import json as _json

        parsed = _json.loads(s)
        if not isinstance(parsed, dict):
            raise ValueError(
                'FORGE_CONNECTOR_OAUTH_APPS must be a JSON object, e.g. '
                '{"google":{"client_id":"...","client_secret":"..."}}'
            )
        out: dict[str, dict] = {}
        for group, creds in parsed.items():
            if not isinstance(creds, dict):
                raise ValueError(f"FORGE_CONNECTOR_OAUTH_APPS['{group}'] must be an object of credential values")
            out[str(group)] = {str(k): str(val) for k, val in creds.items()}
        return out

    # --- App ---
    app_name: str = "Alberto"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/v1"

    # --- Persistence (SQLite) ---
    database_url: str = Field(default_factory=_default_database_url)
    # LangGraph durable-execution checkpointer (sqlite file or 'memory').
    checkpoint_db: str = Field(default_factory=_default_checkpoint_db)
    # Dedicated SQLite file for background worker job queue
    queue_db_path: str = Field(default_factory=_default_queue_db)
    queue_poll_interval: float = 1.0
    worker_lease_timeout_seconds: int = 300
    worker_retry_backoff_base_seconds: float = 2.0

    # --- Vectors (embedded persistent Chroma) ---
    chroma_path: str = Field(default_factory=_default_chroma_path)
    # Cache dir for the local fastembed embedder's model files. Set to a baked path in the
    # Docker image (see apps/api/Dockerfile) so the default model ships with the image - no
    # first-run download / network dependency. None -> fastembed's own default (a temp dir),
    # fine for local dev.
    fastembed_cache_dir: str | None = None

    # --- Knowledge Graph (embedded LadybugDB) ---
    ladybug_path: str = Field(default_factory=_default_ladybug_path)
    ladybug_buffer_pool_size_mb: int = 256

    # --- Memory Learning (Milestone 2.1 toggle, disabled by default) ---
    memory_learning_enabled: bool = False
    memory_learning_timeout_seconds: float = 30.0
    memory_learning_max_retries: int = 3


    # --- Secrets (Fernet master key; file-backed locally, KMS/Vault in prod) ---
    secret_key_file: str = Field(default_factory=_default_secret_key_file)

    # --- Platform auth (JWT) ---
    jwt_secret: str = "dev-insecure-change-me"
    # Previously-active signing secrets, still ACCEPTED for verification (not for minting),
    # so you can rotate `jwt_secret` without invalidating every live token: set the new key
    # here-as-previous during the overlap window, then drop it. Tokens carry a `kid` header.
    jwt_secret_previous: Annotated[list[str], NoDecode] = []
    jwt_key_id: str = "k1"
    jwt_algorithm: str = "HS256"
    # Shorter access-token lifetime bounds the blast radius of a leaked token (audit S11);
    # the 30-day refresh token (rotated on use) keeps sessions alive without re-login.
    access_token_ttl_minutes: int = 60 * 8
    refresh_token_ttl_days: int = 30
    # Static service token for trusted server-to-server integrations (e.g. an app backend that
    # drives runs on behalf of its users). Sent as `Authorization: Bearer <token>`; when it
    # matches, the request authenticates as a least-privilege (editor) service identity in the
    # seeded workspace - no expiry, revoke by rotating this value. Empty = disabled. This is the
    # outer "is this call from our backend?" barrier; per-user / per-API auth is handled
    # separately (e.g. session+CSRF injected per-run into tools). Keep it long, random, secret.
    service_api_token: str = ""
    # Auth is ON by default - the app behaves like production (real login required), so the
    # flow is actually exercised in dev. The seeded owner (bootstrap_admin_email/password
    # below) lets you log in immediately; self-service signup creates additional workspaces.
    # (Public surfaces - webhooks/MCP/OAuth callback - authenticate by their own key,
    # never the JWT, so they keep working regardless.)
    auth_required: bool = True
    # Explicit development shortcut only: when auth_required is false in a local dev environment,
    # allows anonymous requests to receive owner role. False by default (anonymous requests receive
    # the unprivileged 'viewer' role). Never permitted outside local development.
    dev_allow_anonymous_owner: bool = False
    # Allow open self-service signup. When False, only an existing admin can invite users.
    allow_open_signup: bool = True
    # Public base URL of THIS API (for OAuth redirect URIs + channel webhooks). Must match
    # what you register with each OAuth provider, e.g. https://forge.yourco.com.
    public_base_url: str = "http://localhost:8000"
    # Public URL of the web console (where the SPA is served). Used to build invite links
    # emailed to new teammates, e.g. https://app.forge.yourco.com.
    public_console_url: str = "http://localhost:3000"

    # Deployment-wide fallback for a per-user auth provider's `token_ctx_key`. When a per-user
    # bearer provider does NOT set its own `token_ctx_key`, the resolver reads the forwarded inline
    # token from THIS run-context key (sent by a server-to-server caller in `X-Forge-Context`). Lets
    # an integration that always forwards the same key (e.g. {"user_token": "..."}) work in EVERY
    # project without configuring each provider by hand (survives project re-creation).
    # Empty/None = off (per-provider `token_ctx_key` only). Env: FORGE_DEFAULT_TOKEN_CTX_KEY.
    default_token_ctx_key: str | None = None

    # --- Outbound email (SMTP) - used for team invites & notifications. When smtp_host is
    # unset, email sending is a no-op and the API returns the invite link so an admin can
    # share it manually. Point at any SMTP relay (Postmark/SendGrid/SES/Mailgun/etc.). ---
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from: str = "Forge <no-reply@forge.local>"
    # The seeded workspace owner. Default dev credentials: admin / password.
    bootstrap_admin_email: str = "admin"
    bootstrap_admin_password: str | None = "password"

    # --- Schemas (shared contract, packages/schemas) ---
    schemas_dir: str = Field(default_factory=lambda: _DEFAULT_SCHEMAS_DIR.as_posix())

    # --- Tools ---
    # Per-environment substitution values exposed to tool/auth endpoint templates as {{env.*}}
    # (e.g. {{env.api_base}} in a REST tool's url_template, or a GraphQL endpoint). ONE JSON map,
    # so the SAME tool/auth DB row works in every environment - only this value changes per deploy.
    # Add one entry per downstream system. A template that references a key NOT in this map fails
    # the call with a clear error (rather than silently sending a broken URL).
    # Env: FORGE_TOOL_VARS='{"api_base":"https://api.example.com"}'. Blank/unset = {}.
    tool_vars: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    # --- Connector OAuth apps (deployment-wide) -------------------------------------------
    # Pre-registered vendor OAuth apps, keyed by a connector's `credential_group`. When a group
    # is present here, installing any connector in that family asks the operator for NOTHING:
    # the install seeds the project's credentials from this map and the user goes straight to
    # "Connect account" -> vendor consent screen -> done. That is the one-click experience.
    #
    # Register ONE app per vendor for the whole deployment (or per fleet), with
    # <FORGE_PUBLIC_BASE_URL>/v1/oauth/callback as its redirect URI. For Google that means a
    # "Web application" OAuth client: only that client type has an Authorized redirect URIs
    # field, and Forge's callback is a real https path on the API's own origin, not a loopback
    # address. (A Desktop client cannot register it at all - the sign-in then fails with
    # redirect_uri_mismatch.) Each connector's `setup_help` says the same thing; keep them
    # in step.
    #
    # Env: FORGE_CONNECTOR_OAUTH_APPS='{"google":{"client_id":"...","client_secret":"..."}}'
    # Unset = each project registers its own app and pastes the credentials (previous behavior).
    connector_oauth_apps: Annotated[dict[str, dict], NoDecode] = Field(default_factory=dict)
    # Code tools run RestrictedPython (AST-sandboxed) but NOT OS-isolated: no CPU/memory
    # bound and a runaway thread can't be force-killed. RestrictedPython is a hardening
    # layer, not a sandbox, so it is OFF by default. Only enable it on a trusted, single-
    # tenant install, or once an isolated executor (subprocess/container/gVisor) is wired
    # in. The production guard refuses to boot with this on unless explicitly acknowledged.
    enable_code_tools: bool = False
    # Set true to run code tools in production despite the lack of OS isolation (you accept
    # the in-process RCE/DoS risk - e.g. a trusted single-tenant deployment).
    allow_unsandboxed_code_tools: bool = False
    # External MCP servers reached via the `stdio` transport launch a LOCAL PROCESS
    # (command + args) - i.e. arbitrary command execution on the API host, like an
    # unsandboxed code tool. OFF by default; enable only on a trusted single-tenant install.
    # Optionally restrict to an allow-list of executables (empty = any command when enabled).
    enable_mcp_stdio: bool = False
    mcp_stdio_allowed_commands: Annotated[list[str], NoDecode] = []
    # Prune the assistant's ~19 tools to the relevant subset per turn (cuts tool-schema
    # tokens). Opt-in: the selection itself is an extra model call, so it's a tradeoff.
    assistant_tool_selector: bool = False
    # Hard cap on a tool response handed to the model when no projection trims it
    # (token-cost guard). 0 = no cap.
    max_tool_response_chars: int = 20000
    # Default per-request timeout (seconds) for REST/HTTP tools when the tool config doesn't
    # set its own `timeout_seconds`.
    tool_request_timeout_seconds: int = 30
    # SQL query timeout (seconds) for database tools when not overridden.
    sql_tool_timeout_seconds: int = 30
    # MCP remote invocation timeout (seconds) for external MCP tools.
    mcp_tool_timeout_seconds: int = 30
    # Max redirect hops a REST tool follows when follow_redirects is on. Each hop is
    # re-validated against the SSRF egress guard, so this bounds a redirect loop / chain.
    tool_max_redirects: int = 5
    # Best-effort IPv6/AAAA-lookup suppression fallback (see forge.util.netfix). The AUTHORITATIVE
    # fix for the slow-cold-DNS penalty is `RES_OPTIONS=no-aaaa` in the process env, set by
    # docker-compose - it works under uvloop (which the server uses) where a Python resolver patch
    # cannot. This toggle only enables the code-level fallback for launch paths without that env
    # var (e.g. a local .venv run). Disable (FORGE_PREFER_IPV4_EGRESS=false) for an IPv6-only egress
    # network (and clear RES_OPTIONS in that case too).
    prefer_ipv4_egress: bool = True
    # Reuse ONE warm keep-alive HTTP connection pool for OpenAI model calls across runs, instead
    # of the fresh client each per-run graph compile would otherwise build (a new TLS handshake on
    # the first call of every run). No cost/token impact - purely a transport optimization that
    # also lowers server load (fewer handshakes/sockets). Off => each model builds its own client.
    llm_http_keepalive: bool = True
    # Auto-attach AnthropicPromptCachingMiddleware to Anthropic-model agents (caches the
    # static system-prompt/tools prefix; large multi-turn cost saving). Off => opt-in only.
    default_anthropic_prompt_caching: bool = True
    # Minimum cosine similarity for a long-term-memory `recall` hit to be returned. 0 = off
    # (return the top_k nearest regardless of distance). Raise (~0.3-0.5 for the default BGE
    # embedder) to stop unrelated memories polluting the prompt.
    memory_recall_min_score: float = 0.0

    # --- Semantic cache / HITL / channel delivery (framework-configurable) ---
    # Cosine threshold for a semantic-cache hit (the `semantic_cache` agent middleware) and its
    # entry TTL. Per-agent config can override; these are the deployment defaults.
    semantic_cache_threshold: float = 0.95
    semantic_cache_ttl_seconds: int = 3600
    # How long a HITL-interrupted run may wait for a human before the reaper expires it (fails
    # the run + closes the handoff with the on_error fallback). 0 = never expire (prior behavior).
    hitl_approval_timeout_seconds: int = 0
    # Hard per-run wall-clock ceiling. 0 = unlimited. Default 300s (5m).
    run_wall_clock_timeout_seconds: int = 300
    # Execution safety limits for ReAct agent loops
    max_model_calls_per_run: int = 25
    max_tool_calls_per_run: int = 50
    max_repeated_no_progress_calls: int = 3
    # SSE event buffer max size (ring buffer to prevent OOM)
    sse_event_buffer_size: int = 1000
    # Outbound channel delivery (email SMTP) retry policy.
    channel_send_max_attempts: int = 3
    channel_send_backoff_base_seconds: float = 0.5

    # --- Models ---
    default_model: str = "fake:echo"  # offline-safe default; set a real provider model in prod
    request_timeout_seconds: int = 600

    # LangGraph checkpoint durability for runs: "async" (default - persist while the
    # next step executes), "sync" (persist before next step), or "exit" (persist only
    # at the end; fastest, but HITL interrupts mid-run rely on per-step checkpoints,
    # so keep async/sync when using human_input nodes).
    run_durability: str = "async"
    # Floor for LangGraph's per-run superstep budget (recursion_limit). LangGraph's own
    # default is 25, which a Loop node (each iteration ~= loop->router->body, ~3 supersteps)
    # blows past after only a handful of iterations, raising GraphRecursionError mid-run. The
    # actual limit used is max(this floor, a value derived from workflow size + loop max_iter),
    # so large graphs/loops scale automatically. Raise the floor for very deep workflows.
    graph_recursion_limit: int = 100

    # --- Observability (OpenTelemetry export; point at an OTLP collector or Langfuse) ---
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "forge"
    # Expose the unauthenticated /metrics (Prometheus counters) and /version (dependency
    # versions) endpoints. OFF by default: these are an internal operational surface that also
    # aids fingerprinting, so enable only where the scrape endpoint sits on a trusted network.
    expose_metrics: bool = False

    # --- Tool I/O in traces (debug what an agent actually sent a tool) ---
    # Master switch: capture per-tool-call input/output on trace spans (the LLM's tool args,
    # and for REST tools the FRAMED request - method, resolved URL, query, headers, cookies,
    # body - plus the response status/latency/body). Lets you see whether the agent attached
    # proper input, and why a call that "works in test" 401s in a run (e.g. a {{ctx.*}} cookie
    # that never arrived and was silently dropped). Admin-only dashboard surface.
    trace_tool_io: bool = True
    # A REST request/response captured for a trace can contain LIVE session cookies, CSRF
    # tokens, and Authorization headers. Off (default) stores full values for debugging; set
    # true on a shared/production install to MASK the values of sensitive headers/cookies
    # (presence + length kept, e.g. "••• (32 chars)") so secrets aren't persisted in traces.
    trace_tool_io_redact: bool = False
    # Per-field clip so a large body/response can't bloat the spans table. 0 = no cap.
    trace_tool_io_max_chars: int = 20000

    # In-process scheduler for `schedule` / `app_event` triggers (fires due ones once a minute).
    # ON by default so a published schedule actually fires out of the box (the manual documents
    # this; off-by-default silently no-op'd every schedule). Dispatch now claims each due trigger
    # atomically (re-check + stamp last_fired_at in one txn) before running it, so an accidental
    # multi-leader setup can't double-fire. For multi-replica prod, still elect ONE leader:
    # `scheduler_leader` lets you ship the same image everywhere and set FORGE_SCHEDULER_LEADER
    # =false on the non-leaders. Set FORGE_ENABLE_SCHEDULER=false to disable entirely.
    enable_scheduler: bool = True
    scheduler_leader: bool = True

    # Seed demo data (projects/tools/auth) on first run. Off => start from an empty
    # workspace and create projects yourself. Set FORGE_SEED_DEMO=true to populate.
    seed_demo: bool = False

    # --- Versioning (entity change history) ---
    # How many recent versions to retain per entity (workflows, agents, tools, components,
    # auth providers, knowledge sources, project settings). Older versions are pruned on each
    # new snapshot. 0 = keep all (no pruning). Overridable per-tenant via tenant.settings
    # ("version_history_limit"); exposed in the console Settings > Versioning panel.
    version_history_limit: int = 5

    # --- CORS ---
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # --- Egress / SSRF guard (applies to REST/GraphQL tools, webhooks, web_fetch,
    # URL ingestion, and auth/OAuth token fetches). block_private rejects URLs that
    # resolve to private/loopback/link-local/metadata addresses. allow/deny host
    # lists match a host or any parent domain (e.g. "example.com" covers
    # "api.example.com"). Per-project overrides live in project.config.egress. ---
    egress_block_private: bool = True
    egress_allow_hosts: Annotated[list[str], NoDecode] = []
    egress_deny_hosts: Annotated[list[str], NoDecode] = []
    # Hosts permitted to resolve to a PRIVATE / loopback / link-local address even while
    # block_private is on (default-deny, explicit-allow). Use for trusted internal targets -
    # localhost during dev, an internal service, an on-prem host - WITHOUT disabling the SSRF
    # guard globally (so the app still boots in production). Matches a host or any parent
    # domain. Per-project override: project.config.egress.allow_private_hosts.
    egress_allow_private_hosts: Annotated[list[str], NoDecode] = []

    # --- Rate limits / quotas (per tenant). 0 = unlimited. Per-tenant overrides may
    # live in tenant.settings (max_runs_per_minute / max_runs_per_day). ---
    run_rate_limit_per_minute: int = 60
    api_rate_limit_per_minute: int = 240
    # Ceiling on the UNAUTHENTICATED auth endpoints (login/register/refresh/accept-invite) -
    # brute-force / credential-stuffing guard (audit: login had no throttle). This is the STRICT
    # per-EMAIL rate (per-account guard); the per-IP bucket is 10x looser (stuffing/DoS across
    # many accounts). 0 = unlimited.
    auth_rate_limit_per_minute: int = 10
    # Wire api_rate_limit_per_minute as a global per-IP request ceiling (ASGI middleware).
    # Health/readiness/metrics and SSE stream paths are exempt. Set false to disable the
    # global guard (per-surface limits - runs/embed/auth/tools - still apply).
    enable_global_rate_limit: bool = True
    # Projected per-run cost (USD) reserved against the daily cost cap while a run is in flight,
    # so N concurrent runs can't each pass a stale "already-spent" check and blow past the cap.
    # 0 = disabled (admit on completed-cost only, prior behavior). Per-tenant override:
    # tenant.settings["projected_run_cost_usd"] / ["max_cost_per_run_usd"].
    projected_run_cost_usd: float = 0.0
    # Timezone for the daily quota reset window (was hard-coded to UTC midnight). Per-tenant
    # override: tenant.settings["reset_tz"]. Falls back to UTC where tzdata is unavailable.
    quota_reset_tz: str = "UTC"
    # Bounded concurrency for evaluation runs (each dataset item is a full billable run).
    eval_concurrency: int = 5

    # Max concurrent in-flight runs per tenant (0 = unlimited). Backpressure / noisy-
    # neighbour guard for the inline execution path until the worker tier is enabled.
    max_concurrent_runs_per_tenant: int = 20

    # How many recent turns (Trace rows) the Traces conversation list scans before grouping
    # by thread in Python. Bounds the query regardless of retention; raise it for projects
    # with very deep history at the cost of a wider scan.
    conversation_scan_limit: int = 2000

    # --- Data retention (scheduled purge; leader-only, wired into the reaper loop). Traces/
    # spans/runs are purged per-project by project.config.tracing.retention_days; audit logs by
    # audit_log_retention_days. 0 anywhere = keep forever (no purge). ---
    enable_retention: bool = True
    retention_interval_seconds: int = 3600  # how often the purge sweep runs
    audit_log_retention_days: int = 0       # workspace-wide audit-log floor; 0 = keep forever
    # Fallback trace/span/run retention (days) for projects that don't set
    # tracing.retention_days in their config. 0 = keep forever.
    default_trace_retention_days: int = 0

    # Reverse-proxy IPs whose X-Forwarded-For we trust for client-IP derivation. Empty =>
    # trust none (use the socket peer). Set to your LB/ingress IPs in production so clients
    # can't spoof their IP for per-IP rate limits / audit. "*" trusts any (only behind a
    # trusted ingress that always overwrites XFF).
    trusted_proxies: Annotated[list[str], NoDecode] = []

    # Host allow-list for the API (TrustedHostMiddleware). Empty => allow any (dev).
    trusted_hosts: Annotated[list[str], NoDecode] = []

    # --- LangGraph checkpointer backend: "sqlite" (default local), "memory" (tests / ephemeral) ---
    checkpoint_backend: str = "sqlite"

    @property
    def data_dir(self) -> Path:
        return _get_logical_data_root()

    def ensure_dirs(self) -> None:
        root = self.data_dir
        for sub in (root, root / "db", root / "db" / "ladybug", root / "chroma", root / "memory", root / "logs", root / "config"):
            sub.mkdir(parents=True, exist_ok=True)
        Path(self.chroma_path).mkdir(parents=True, exist_ok=True)
        Path(self.ladybug_path).mkdir(parents=True, exist_ok=True)

    # Environments treated as local/insecure-OK. ANY other value (staging, prod, an
    # unknown string, or the empty string) is treated as security-enforced - so a
    # misconfigured/typo'd FORGE_ENVIRONMENT fails CLOSED rather than silently skipping
    # every guard.
    _DEV_ENVIRONMENTS = ("development", "dev", "local", "test")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    @property
    def enforce_security(self) -> bool:
        """True when the deployment must pass the hardening checks. Only the explicit
        local-dev environment names opt out; everything else fails closed."""
        return self.environment.lower() not in self._DEV_ENVIRONMENTS

    def validate_production(self) -> list[str]:
        """Return a list of FATAL misconfigurations. Called at startup; an install with
        any of these should refuse to serve. Enforced for every non-dev environment
        (fail-closed), not just literal 'production'."""
        problems: list[str] = []
        if not self.enforce_security:
            return problems
        if self.jwt_secret in ("", "dev-insecure-change-me"):
            problems.append("FORGE_JWT_SECRET is unset/default - set a strong random secret.")
        if not self.auth_required:
            problems.append("FORGE_AUTH_REQUIRED must be true outside local development.")
        if self.dev_allow_anonymous_owner:
            problems.append("FORGE_DEV_ALLOW_ANONYMOUS_OWNER must be false outside local development.")
        if self.bootstrap_admin_password == "forge-admin":
            problems.append("FORGE_BOOTSTRAP_ADMIN_PASSWORD is the dev default - set a real one.")
        if not self.egress_block_private:
            problems.append("FORGE_EGRESS_BLOCK_PRIVATE must stay true outside dev (SSRF guard).")

        if self.enable_code_tools and not self.allow_unsandboxed_code_tools:
            problems.append(
                "FORGE_ENABLE_CODE_TOOLS is on but code execution is not OS-isolated. Disable it, "
                "or set FORGE_ALLOW_UNSANDBOXED_CODE_TOOLS=true to explicitly accept the RCE/DoS risk."
            )
        # A Host-header allow-list must be set outside dev (empty => TrustedHostMiddleware is
        # not even added, so Host/absolute-URI spoofing is unmitigated - audit S6/host attacks).
        if not self.trusted_hosts:
            problems.append("FORGE_TRUSTED_HOSTS must list the API's public hostname(s) outside dev.")
        # Public URLs are embedded in OAuth redirect URIs and emailed invite/reset links; they
        # MUST be https in production so tokens/codes never traverse cleartext.
        for name, url in (("FORGE_PUBLIC_BASE_URL", self.public_base_url),
                          ("FORGE_PUBLIC_CONSOLE_URL", self.public_console_url)):
            if not url.lower().startswith("https://"):
                problems.append(f"{name} must be an https:// URL outside dev (got {url!r}).")
        # A short service token is brute-forceable; if enabled at all it must be long+random.
        if self.service_api_token and len(self.service_api_token) < _MIN_SERVICE_TOKEN_LEN:
            problems.append(
                f"FORGE_SERVICE_API_TOKEN is set but shorter than {_MIN_SERVICE_TOKEN_LEN} chars - "
                "use a long random secret or leave it empty to disable server-to-server auth."
            )
        return problems

    def startup_warnings(self) -> list[str]:
        """Non-fatal but dangerous configuration, logged loudly at startup regardless of
        environment so an insecure local default is never silently shipped."""
        warns: list[str] = []
        if self.jwt_secret == "dev-insecure-change-me":
            warns.append("JWT secret is the built-in dev default - tokens are forgeable. Set FORGE_JWT_SECRET.")
        if self.bootstrap_admin_password == "forge-admin":
            warns.append("Bootstrap admin password is the dev default. Set FORGE_BOOTSTRAP_ADMIN_PASSWORD.")
        if not self.auth_required:
            warns.append("auth_required is false - unauthenticated requests receive viewer role (or owner if dev_allow_anonymous_owner).")
        if self.dev_allow_anonymous_owner:
            warns.append("dev_allow_anonymous_owner is true - unauthenticated requests receive owner role in dev.")
        if self.enable_code_tools:
            warns.append("Code tools are enabled and run unsandboxed (RestrictedPython only).")
        if self.enable_mcp_stdio:
            warns.append(
                "MCP stdio transport is enabled - external MCP clients can launch local processes "
                "(arbitrary command execution). Restrict FORGE_MCP_STDIO_ALLOWED_COMMANDS."
            )
        if self.environment.lower() not in (*self._DEV_ENVIRONMENTS, "production", "prod", "staging"):
            warns.append(f"Unrecognized FORGE_ENVIRONMENT={self.environment!r} - treated as security-enforced.")
        return warns


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
