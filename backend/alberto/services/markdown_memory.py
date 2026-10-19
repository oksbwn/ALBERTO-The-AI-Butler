"""Persistent Markdown Memory: Durable, human-readable projections under /data/memory.

Key principles:
- Scoped strictly to /data/memory/<tenant_id>/<project_id>/
- Path traversal prevention
- Atomic file writes via temporary files and os.replace
- UTF-8 encoding
- SQLite is authoritative; Markdown files are structured projections of active memories.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alberto.config import settings

logger = logging.getLogger("alberto.services.markdown_memory")

CATEGORY_TO_FILE: dict[str, tuple[str, str]] = {
    "preference": ("preferences.md", "User Preferences"),
    "preferences": ("preferences.md", "User Preferences"),
    "technical_preference": ("preferences.md", "User Preferences"),
    "profile": ("profile.md", "User Profile"),
    "user_profile": ("profile.md", "User Profile"),
    "home": ("home.md", "Home Setup"),
    "home_setup": ("home.md", "Home Setup"),
    "device": ("technology.md", "Technology & Devices"),
    "application": ("technology.md", "Technology & Devices"),
    "technology": ("technology.md", "Technology & Devices"),
    "project": ("projects.md", "Projects & Workflows"),
    "projects": ("projects.md", "Projects & Workflows"),
    "routine": ("home.md", "Home Setup"),
    "rule": ("preferences.md", "User Preferences"),
    "instruction": ("preferences.md", "User Preferences"),
}

DEFAULT_FILE = ("general.md", "General Knowledge")


class MarkdownMemoryService:
    """Manages persistent markdown memory files under /data/memory."""

    _base_dir_override: Path | None = None

    @classmethod
    def get_base_dir(cls) -> Path:
        if cls._base_dir_override is not None:
            cls._base_dir_override.mkdir(parents=True, exist_ok=True)
            return cls._base_dir_override.resolve()
        base = (settings.data_dir / "memory").resolve()
        base.mkdir(parents=True, exist_ok=True)
        return base

    @classmethod
    def get_project_dir(cls, tenant_id: str, project_id: str) -> Path:
        base = cls.get_base_dir()
        if ".." in tenant_id or ".." in project_id or "/" in tenant_id or "\\" in tenant_id:
            raise ValueError(f"Path traversal detected: {tenant_id}/{project_id}")
        clean_tenant = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", tenant_id)
        clean_project = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", project_id)
        target = (base / clean_tenant / clean_project).resolve()
        try:
            target.relative_to(base)
        except ValueError as e:
            raise ValueError(f"Path traversal detected: {tenant_id}/{project_id}") from e
        target.mkdir(parents=True, exist_ok=True)
        return target

    @classmethod
    def _resolve_file_for_kind(cls, kind: str) -> tuple[str, str]:
        normalized = (kind or "").strip().lower()
        return CATEGORY_TO_FILE.get(normalized, DEFAULT_FILE)

    @classmethod
    def sync_memory(
        cls,
        tenant_id: str,
        project_id: str,
        memory_id: str,
        text: str,
        kind: str,
        confidence: float = 1.0,
        status: str = "active",
    ) -> Path:
        """Add, update, or remove a memory line in the appropriate markdown file.
        Uses atomic file writing to prevent corruption."""
        proj_dir = cls.get_project_dir(tenant_id, project_id)
        filename, title = cls._resolve_file_for_kind(kind)
        target_path = proj_dir / filename

        lines: list[str] = []
        if target_path.exists():
            try:
                lines = target_path.read_text(encoding="utf-8").splitlines()
            except Exception as e:
                logger.warning("Failed to read %s: %s", target_path, e)
                lines = []

        now_iso = datetime.now(UTC).isoformat()
        mem_tag = f"[mem:{memory_id}]"

        # Filter or update existing entry
        new_lines: list[str] = []
        found = False

        for line in lines:
            if line.startswith("Last updated:"):
                continue  # will rewrite timestamp
            if mem_tag in line:
                found = True
                if status == "active":
                    conf_str = f" (confidence: {confidence:.2f})" if confidence < 1.0 else ""
                    new_lines.append(f"- {mem_tag} {text.strip()}{conf_str}")
                # if superseded or deleted, line is dropped (not added)
                continue
            new_lines.append(line)

        if not found and status == "active":
            conf_str = f" (confidence: {confidence:.2f})" if confidence < 1.0 else ""
            new_lines.append(f"- {mem_tag} {text.strip()}{conf_str}")

        # Ensure title and timestamp at top
        final_content: list[str] = [
            f"# {title}",
            f"Last updated: {now_iso}",
            "",
        ]

        # Add remaining non-header lines
        content_items = [
            item for item in new_lines
            if not item.startswith("# ") and not item.startswith("Last updated:") and item.strip()
        ]
        final_content.extend(content_items)
        final_content.append("")  # trailing newline

        cls._atomic_write(target_path, "\n".join(final_content))
        return target_path

    @classmethod
    def remove_memory(
        cls,
        tenant_id: str,
        project_id: str,
        memory_id: str,
        kind: str | None = None,
    ) -> None:
        """Remove memory entry across files."""
        proj_dir = cls.get_project_dir(tenant_id, project_id)
        files_to_check = [proj_dir / cls._resolve_file_for_kind(kind)[0]] if kind else list(proj_dir.glob("*.md"))

        mem_tag = f"[mem:{memory_id}]"
        now_iso = datetime.now(UTC).isoformat()

        for p in files_to_check:
            if not p.exists():
                continue
            lines = p.read_text(encoding="utf-8").splitlines()
            if any(mem_tag in line_item for line_item in lines):
                filtered = [line_item for line_item in lines if mem_tag not in line_item and not line_item.startswith("Last updated:")]
                header = [f"# {p.stem.replace('_', ' ').title()}", f"Last updated: {now_iso}", ""]
                body = [line_item for line_item in filtered if not line_item.startswith("# ") and line_item.strip()]
                cls._atomic_write(p, "\n".join(header + body + [""]))

    @classmethod
    def list_files(cls, tenant_id: str, project_id: str) -> list[dict[str, Any]]:
        """List all markdown files in the project memory directory."""
        proj_dir = cls.get_project_dir(tenant_id, project_id)
        result = []
        for p in sorted(proj_dir.glob("*.md")):
            stat = p.stat()
            updated_iso = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
            result.append({
                "filename": p.name,
                "category": p.stem,
                "size_bytes": stat.st_size,
                "updated_at": updated_iso,
                "path": str(p),
            })
        return result

    @classmethod
    def read_file(cls, tenant_id: str, project_id: str, filename: str) -> str | None:
        """Read content of a specific markdown memory file with traversal protection."""
        proj_dir = cls.get_project_dir(tenant_id, project_id)
        clean_name = Path(filename).name
        target = (proj_dir / clean_name).resolve()
        try:
            target.relative_to(proj_dir)
        except ValueError:
            return None
        if not target.exists() or not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    @classmethod
    def _atomic_write(cls, target_path: Path, content: str) -> None:
        """Write content to a .tmp file first, then atomically rename."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_suffix(f".tmp.{os.getpid()}")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(tmp_path, target_path)
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise
