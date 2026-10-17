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
