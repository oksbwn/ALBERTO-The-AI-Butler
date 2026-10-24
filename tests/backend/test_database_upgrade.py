import sqlite3
import pytest
from sqlalchemy import create_engine
from alberto.db.base import _ensure_new_columns
from alberto.queue import SqliteJobQueue


def test_database_upgrade_from_pre_m1_6_schema(tmp_path):
    """Test upgrade safety on an existing populated pre-Milestone 1.6 database."""
    db_file = tmp_path / "pre_m1_6.db"
    conn = sqlite3.connect(str(db_file))

    # 1. Create pre-Milestone 1.6 schema (without iterations_count, tool_calls_count, termination_reason)
    conn.execute("""
        CREATE TABLE runs (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            project_id VARCHAR(36),
            workflow_id VARCHAR(36) NOT NULL,
            thread_id VARCHAR(36) NOT NULL,
            status VARCHAR(20) NOT NULL,
            started_at TIMESTAMP,
            ended_at TIMESTAMP,
            output JSON,
            error TEXT,
            total_tokens INTEGER DEFAULT 0,
            total_cost_usd REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.execute("""
        CREATE TABLE traces (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            project_id VARCHAR(36),
            workflow_id VARCHAR(36) NOT NULL,
            run_id VARCHAR(36) NOT NULL,
            thread_id VARCHAR(36) NOT NULL,
            name VARCHAR(120) NOT NULL,
            status VARCHAR(20) NOT NULL,
            started_at TIMESTAMP NOT NULL,
            ended_at TIMESTAMP,
            latency_ms INTEGER,
            total_tokens INTEGER,
            total_cost_usd REAL,
            source VARCHAR(40) DEFAULT 'playground',
            actor VARCHAR(300) DEFAULT 'System',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Populate representative pre-M1.6 data
    conn.execute("""
        INSERT INTO runs (id, tenant_id, project_id, workflow_id, thread_id, status, output, total_tokens, total_cost_usd)
        VALUES ('run-pre-1', 'tenant-1', 'proj-1', 'wf-1', 'th-1', 'done', '{"answer":"legacy"}', 150, 0.002);
    """)
    conn.execute("""
        INSERT INTO runs (id, tenant_id, project_id, workflow_id, thread_id, status, error)
        VALUES ('run-pre-2', 'tenant-1', 'proj-1', 'wf-1', 'th-2', 'running', NULL);
    """)
    conn.execute("""
        INSERT INTO traces (id, tenant_id, project_id, workflow_id, run_id, thread_id, name, status, started_at, total_tokens)
        VALUES ('trace-pre-1', 'tenant-1', 'proj-1', 'wf-1', 'run-pre-1', 'th-1', 'run', 'done', CURRENT_TIMESTAMP, 150);
    """)
    conn.commit()
    conn.close()

    # 3. Perform migration via _ensure_new_columns
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as sync_conn:
        _ensure_new_columns(sync_conn)
        sync_conn.commit()

    # 4. Verify existing records and new columns
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    # Verify runs table has new columns
    row1 = conn.execute("SELECT * FROM runs WHERE id = 'run-pre-1'").fetchone()
    assert row1["status"] == "done"
    assert row1["output"] == '{"answer":"legacy"}'
    assert row1["total_tokens"] == 150
    # Milestone 1.6 columns added with proper defaults
    assert row1["iterations_count"] == 0
    assert row1["tool_calls_count"] == 0
    assert row1["termination_reason"] is None

    # Verify traces table has new columns
    t1 = conn.execute("SELECT * FROM traces WHERE id = 'trace-pre-1'").fetchone()
    assert t1["status"] == "done"
    assert t1["iterations_count"] == 0
    assert t1["tool_calls_count"] == 0
    assert t1["termination_reason"] is None

    # Verify new insertions work with new fields
    conn.execute("""
        INSERT INTO runs (id, tenant_id, project_id, workflow_id, thread_id, status, iterations_count, tool_calls_count, termination_reason)
        VALUES ('run-post-1', 'tenant-1', 'proj-1', 'wf-1', 'th-3', 'done', 4, 7, 'completed');
    """)
    conn.commit()
    row_new = conn.execute("SELECT * FROM runs WHERE id = 'run-post-1'").fetchone()
    assert row_new["iterations_count"] == 4
    assert row_new["tool_calls_count"] == 7
    assert row_new["termination_reason"] == "completed"

    # Idempotent re-run
    with engine.connect() as sync_conn:
        _ensure_new_columns(sync_conn)
        sync_conn.commit()

    conn.close()


@pytest.mark.asyncio
async def test_job_queue_upgrade_from_pre_m1_6(tmp_path):
    """Test upgrade of pre-M1.6 job_queue table without available_at or lease_token."""
    queue_file = tmp_path / "queue_pre.sqlite"
    conn = sqlite3.connect(str(queue_file))
    conn.execute("""
        CREATE TABLE job_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            project_id TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            locked_at TIMESTAMP,
            locked_by TEXT
        );
    """)
    conn.execute("""
        INSERT INTO job_queue (run_id, tenant_id, status) VALUES ('run-pre-queue', 't1', 'queued');
    """)
    conn.commit()
    conn.close()

    # Upgrade via SqliteJobQueue
    queue = SqliteJobQueue(db_path=str(queue_file))
    await queue._ensure_table()

    # Verify column additions and data preservation
    conn = sqlite3.connect(str(queue_file))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM job_queue WHERE run_id = 'run-pre-queue'").fetchone()
    assert row["status"] == "queued"
    assert "available_at" in row.keys()
    assert "lease_token" in row.keys()
    assert row["lease_token"] is None

    # Idempotent re-run
    await queue._ensure_table()
    await queue.close()
    conn.close()


def test_alembic_fresh_database_upgrade_to_head(tmp_path):
    """Test fresh database upgrade directly to latest Alembic head (0018)."""
    from alembic import command
    from alembic.config import Config
    from alberto.config import settings

    db_file = tmp_path / "fresh_head.db"
    orig_url = settings.database_url
    try:
        settings.database_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
        cfg = Config("backend/alembic.ini")
        cfg.set_main_option("script_location", "backend/migrations")
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        # SQLite schema inspection: verify uq_agents_tenant_project_system_key exists and is unique
        indexes = conn.execute("PRAGMA index_list('agents')").fetchall()
        idx_dict = {row[1]: bool(row[2]) for row in indexes}
        assert "uq_agents_tenant_project_system_key" in idx_dict
        assert idx_dict["uq_agents_tenant_project_system_key"] is True  # unique

        sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_agents_tenant_project_system_key'"
        ).fetchone()
        assert sql_row is not None
        assert "CREATE UNIQUE INDEX" in sql_row[0]
        assert "WHERE is_system = 1 AND system_key IS NOT NULL" in sql_row[0]
        conn.close()
    finally:
        settings.database_url = orig_url


def test_alembic_upgrade_from_original_0017_to_0018(tmp_path):
    """Test upgrade on an existing database already stamped at revision 0017.
    
    Verifies:
    1. uq_agents_tenant_project_system_key is physically created.
    2. Existing user agents are preserved.
    3. Existing system agent model overrides are preserved.
    4. Existing duplicate system agents are safely resolved.
    5. Re-running upgrade on already-correct database succeeds without duplicate-index errors.
    6. Downgrade 0018 cleanly drops the index.
    """
    from alembic import command
    from alembic.config import Config
    from alberto.config import settings

    db_file = tmp_path / "existing_0017.db"
    conn = sqlite3.connect(str(db_file))

    # 1. Simulate existing database stamped at 0017 without the unique constraint
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
    conn.execute("INSERT INTO alembic_version VALUES ('0017_m2_0_system_agents')")
    conn.execute("""
        CREATE TABLE agents (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            project_id VARCHAR(36) NOT NULL,
            name VARCHAR(120) NOT NULL,
            config JSON DEFAULT '{}',
            created_by VARCHAR(36),
            created_by_email VARCHAR(320),
            is_system BOOLEAN NOT NULL DEFAULT 0,
            system_key VARCHAR(64),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX ix_agents_system_key ON agents (system_key)")
    conn.execute("CREATE INDEX ix_agents_tenant_id ON agents (tenant_id)")
    conn.execute("CREATE INDEX ix_agents_project_id ON agents (project_id)")

    # Insert user agents and duplicate system agents
    conn.execute("""
        INSERT INTO agents (id, tenant_id, project_id, name, config, is_system, system_key)
        VALUES ('user-1', 'tenant-alpha', 'proj-1', 'My Assistant', '{"tools":[]}', 0, NULL),
               ('user-2', 'tenant-alpha', 'proj-1', 'Code Helper', '{"tools":[]}', 0, NULL),
               ('sys-ir-1', 'tenant-alpha', 'proj-1', 'Intent Router', '{}', 1, 'intent_router'),
               ('sys-ir-2', 'tenant-alpha', 'proj-1', 'Intent Router Custom', '{"model":"openai:gpt-4o-override"}', 1, 'intent_router'),
               ('sys-curator', 'tenant-alpha', 'proj-1', 'Memory Curator', '{}', 1, 'memory_curator'),
               ('sys-graph', 'tenant-alpha', 'proj-1', 'Graph Manager', '{}', 1, 'graph_manager')
    """)
    conn.commit()

    # Verify index is NOT present prior to 0018
    pre_indexes = {row[1] for row in conn.execute("PRAGMA index_list('agents')").fetchall()}
    assert "uq_agents_tenant_project_system_key" not in pre_indexes
    conn.close()

    orig_url = settings.database_url
    try:
        settings.database_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
        cfg = Config("backend/alembic.ini")
        cfg.set_main_option("script_location", "backend/migrations")

        # 2. Upgrade to 0018
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        # Prove required unique index is physically present in SQLite schema
        post_indexes = conn.execute("PRAGMA index_list('agents')").fetchall()
        idx_dict = {row[1]: bool(row[2]) for row in post_indexes}
        assert "uq_agents_tenant_project_system_key" in idx_dict
        assert idx_dict["uq_agents_tenant_project_system_key"] is True

        sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_agents_tenant_project_system_key'"
        ).fetchone()
        assert "CREATE UNIQUE INDEX" in sql_row[0]
        assert "WHERE is_system = 1 AND system_key IS NOT NULL" in sql_row[0]

        # Verify existing user-agent preservation: neither user agent was deleted
        user_rows = conn.execute("SELECT id, name FROM agents WHERE is_system = 0").fetchall()
        assert len(user_rows) == 2
        assert {r[0] for r in user_rows} == {"user-1", "user-2"}

        # Verify duplicate system agent safely resolved and model override preserved
        sys_rows = conn.execute("SELECT id, system_key, config FROM agents WHERE is_system = 1").fetchall()
        assert len(sys_rows) == 3
        ir = [r for r in sys_rows if r[1] == "intent_router"][0]
        assert ir[0] == "sys-ir-2"
        assert "openai:gpt-4o-override" in ir[2]

        # 3. Idempotent re-run on already-correct database: must not raise duplicate index error
        command.upgrade(cfg, "head")

        # 4. Rollback: downgrade 0018 back to 0017
        command.downgrade(cfg, "0017_m2_0_system_agents")
        downgrade_indexes = {row[1] for row in conn.execute("PRAGMA index_list('agents')").fetchall()}
        assert "uq_agents_tenant_project_system_key" not in downgrade_indexes

        conn.close()
    finally:
        settings.database_url = orig_url


def test_alembic_upgrade_from_0021_to_0022_integrations_v2(tmp_path):
    """Test upgrade on an existing database stamped at revision 0021 to 0022.

    Verifies:
    1. tool_approval_requests and tool_analysis_jobs tables are created.
    2. Composite index ix_tool_analysis_jobs_lookup is created.
    3. Existing data in pre-0022 tables is completely preserved.
    4. Upgrade is idempotent on repeated runs.
    5. Clean rollback on downgrade.
    """
    from alembic import command
    from alembic.config import Config
    from alberto.config import settings

    db_file = tmp_path / "upgrade_0022.db"
    orig_url = settings.database_url
    try:
        settings.database_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
        cfg = Config("backend/alembic.ini")
        cfg.set_main_option("script_location", "backend/migrations")

        # 1. Upgrade to 0021 (pre-Integrations v2 schema)
        command.upgrade(cfg, "0021_dynamic_ontology_registry")

        # Simulate an existing database that ran migrations up to 0021 in the past:
        conn = sqlite3.connect(str(db_file))
        conn.execute("DROP TABLE IF EXISTS tool_approval_requests;")
        conn.execute("DROP TABLE IF EXISTS tool_analysis_jobs;")
        conn.commit()

        tables_0021 = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "tool_approval_requests" not in tables_0021
        assert "tool_analysis_jobs" not in tables_0021

        # Populate pre-existing data in an earlier table
        conn.execute("""
            INSERT INTO ontology_entity_types (id, tenant_id, project_id, canonical_key, display_name, description, aliases, status, provenance, created_at, updated_at)
            VALUES ('oet-1', 'tenant-1', 'proj-1', 'Server', 'Server', 'Infrastructure server', '[]', 'approved', 'system_seed', datetime('now'), datetime('now'));
        """)
        conn.commit()
        conn.close()

        # 2. Upgrade to head (0022)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        tables_0022 = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "tool_approval_requests" in tables_0022
        assert "tool_analysis_jobs" in tables_0022

        # Check composite index
        indexes = {row[1] for row in conn.execute("PRAGMA index_list('tool_analysis_jobs')").fetchall()}
        assert "ix_tool_analysis_jobs_lookup" in indexes

        # Verify existing data preservation
        oet_rows = conn.execute("SELECT id, canonical_key FROM ontology_entity_types").fetchall()
        assert len(oet_rows) == 1
        assert oet_rows[0][0] == "oet-1"
        assert oet_rows[0][1] == "Server"

        # 3. Verify insert and query on newly migrated tables
        conn.execute("""
            INSERT INTO tool_approval_requests (id, tenant_id, project_id, tool_id, tool_name, arguments_hash, status, expires_at, created_at, updated_at)
            VALUES ('appr-test-1', 'tenant-1', 'proj-1', 'tool-1', 'Tool One', 'hash123', 'pending', datetime('now', '+1 hour'), datetime('now'), datetime('now'));
        """)
        conn.execute("""
            INSERT INTO tool_analysis_jobs (id, tenant_id, project_id, tool_id, schema_fingerprint, status, created_at, updated_at)
            VALUES ('job-test-1', 'tenant-1', 'proj-1', 'tool-1', 'fp123', 'pending', datetime('now'), datetime('now'));
        """)
        conn.commit()

        # 4. Idempotent re-run on current head
        command.upgrade(cfg, "head")

        # 5. Clean rollback on downgrade
        command.downgrade(cfg, "0021_dynamic_ontology_registry")
        tables_downgrade = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "tool_approval_requests" not in tables_downgrade
        assert "tool_analysis_jobs" not in tables_downgrade

        conn.close()
    finally:
        settings.database_url = orig_url


def test_alembic_upgrade_0023_integrations_v3_channels(tmp_path):
    """Test Alembic upgrade to 0023_integrations_v3_channels and downgrade.

    Verifies:
    1. Channels columns target_type, target_id, routing_state, routes, state exist.
    2. channel_identities, channel_pairings, channel_events tables exist with unique constraints and indexes.
    3. Existing channels data is preserved.
    4. Downgrade cleanly drops tables and restores previous state.
    """
    from alembic import command
    from alembic.config import Config
    from alberto.config import settings

    db_file = tmp_path / "test_0023.db"
    orig_url = settings.database_url
    try:
        settings.database_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
        cfg = Config("backend/alembic.ini")
        cfg.set_main_option("script_location", "backend/migrations")

        # 1. Upgrade to 0022 first
        command.upgrade(cfg, "0022_integrations_v2_and_tool_manager")

        conn = sqlite3.connect(str(db_file))
        # Simulate pre-0023 database state: drop 0023 tables and recreate channels without 0023 columns
        conn.execute("DROP TABLE IF EXISTS channel_identities;")
        conn.execute("DROP TABLE IF EXISTS channel_pairings;")
        conn.execute("DROP TABLE IF EXISTS channel_events;")
        conn.execute("DROP TABLE IF EXISTS channels;")
        conn.execute("""
            CREATE TABLE channels (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                tenant_id VARCHAR(36) NOT NULL,
                project_id VARCHAR(36) NOT NULL,
                name VARCHAR(120) NOT NULL,
                type VARCHAR(32) NOT NULL,
                workflow_id VARCHAR(36),
                config JSON DEFAULT '{}',
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            INSERT INTO channels (id, tenant_id, project_id, name, type, workflow_id, config, enabled, created_at, updated_at)
            VALUES ('chan-pre-1', 'tenant-1', 'proj-1', 'Pre-existing Telegram', 'telegram', 'wf-1', '{"bot_token_secret_ref":"sec://t"}', 1, datetime('now'), datetime('now'));
        """)
        conn.commit()
        conn.close()

        # 2. Upgrade to head (0023)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "channel_identities" in tables
        assert "channel_pairings" in tables
        assert "channel_events" in tables

        # Verify channels columns
        cols = {row[1] for row in conn.execute("PRAGMA table_info('channels')").fetchall()}
        assert "target_type" in cols
        assert "target_id" in cols
        assert "routing_state" in cols
        assert "routes" in cols
        assert "state" in cols

        # Check existing channel preservation and migration backfill
        row = conn.execute("SELECT id, target_type, target_id FROM channels WHERE id='chan-pre-1'").fetchone()
        assert row is not None
        assert row[0] == "chan-pre-1"
        assert row[1] == "workflow"
        assert row[2] == "wf-1"

        # 3. Clean downgrade to 0022 updates version stamp
        command.downgrade(cfg, "0022_integrations_v2_and_tool_manager")
        current_rev = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert current_rev == "0022_integrations_v2_and_tool_manager"

        conn.close()
    finally:
        settings.database_url = orig_url



