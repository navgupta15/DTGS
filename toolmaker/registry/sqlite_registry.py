"""
DTGS — SQLite Tool Registry.

Stores ToolSchema records with optional embedding blobs for semantic search.
Falls back to keyword (LIKE) search when no embeddings are present.
"""
from __future__ import annotations

import json
import sqlite3
import struct
import uuid
from pathlib import Path
from typing import Any


# ── Schema ─────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS tools (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    schema_json TEXT NOT NULL,
    source_file TEXT,
    class_name  TEXT,
    method_name TEXT,
    is_rest     INTEGER DEFAULT 0,
    embedding   BLOB,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name);
CREATE INDEX IF NOT EXISTS idx_tools_class ON tools(class_name);
"""


def _pack_embedding(vec: list[float]) -> bytes:
    """Serialize a float list to raw bytes (little-endian float32)."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_embedding(blob: bytes) -> list[float]:
    """Deserialize raw bytes back to float list."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity (avoids numpy dep)."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class ToolRegistry:
    """SQLite-backed tool registry for DTGS."""

    def __init__(self, db_path: str | Path = "dtgs.db") -> None:
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    # ── Write ──────────────────────────────────────────────────────────────

    def upsert_tool(
        self,
        schema: dict,
        source_file: str = "",
        class_name: str = "",
        method_name: str = "",
        is_rest: bool = False,
        embedding: list[float] | None = None,
    ) -> str:
        """Insert or replace a tool record. Returns the tool ID."""
        tool_id = str(uuid.uuid4())
        func = schema.get("function", {})
        name = func.get("name", "unknown")
        description = func.get("description", "")

        emb_blob = _pack_embedding(embedding) if embedding else None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tools
                    (id, name, description, schema_json, source_file,
                     class_name, method_name, is_rest, embedding)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    schema_json=excluded.schema_json,
                    embedding=excluded.embedding
                """,
                (
                    tool_id, name, description, json.dumps(schema),
                    source_file, class_name, method_name,
                    int(is_rest), emb_blob,
                ),
            )
        return tool_id

    def upsert_many(
        self,
        schemas: list[dict],
        embeddings: list[list[float]] | None = None,
        method_meta: list[dict] | None = None,
    ) -> list[str]:
        """
        Bulk upsert list of schemas.

        Args:
            schemas:     list of ToolSchema dicts
            embeddings:  optional parallel list of embedding vectors
            method_meta: optional parallel list of {source_file, class_name,
                         method_name, is_rest} dicts
        """
        ids: list[str] = []
        for i, schema in enumerate(schemas):
            emb = embeddings[i] if embeddings and i < len(embeddings) else None
            meta = method_meta[i] if method_meta and i < len(method_meta) else {}
            tid = self.upsert_tool(
                schema=schema,
                source_file=meta.get("source_file", ""),
                class_name=meta.get("class_name", ""),
                method_name=meta.get("method_name", ""),
                is_rest=meta.get("is_rest", False),
                embedding=emb,
            )
            ids.append(tid)
        return ids

    # ── Read ───────────────────────────────────────────────────────────────

    def keyword_search(self, query: str, top_k: int = 10) -> list[dict]:
        """LIKE search on name + description. Used when no embeddings exist."""
        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT schema_json FROM tools
                WHERE name LIKE ? OR description LIKE ?
                LIMIT ?
                """,
                (pattern, pattern, top_k),
            ).fetchall()
        return [json.loads(r["schema_json"]) for r in rows]

    def semantic_search(
        self, query_embedding: list[float], top_k: int = 10
    ) -> list[dict]:
        """Cosine similarity search over stored embeddings."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT schema_json, embedding FROM tools WHERE embedding IS NOT NULL"
            ).fetchall()

        scored: list[tuple[float, dict]] = []
        for row in rows:
            stored_emb = _unpack_embedding(row["embedding"])
            score = _cosine_similarity(query_embedding, stored_emb)
            scored.append((score, json.loads(row["schema_json"])))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [schema for _, schema in scored[:top_k]]

    def search(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """Unified search: semantic if embedding provided, else keyword."""
        if query_embedding:
            return self.semantic_search(query_embedding, top_k)
        return self.keyword_search(query, top_k)

    def get_all(self, limit: int = 500) -> list[dict]:
        """Return all stored tool schemas."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT schema_json FROM tools LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(r["schema_json"]) for r in rows]

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
