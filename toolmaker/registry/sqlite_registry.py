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

from toolmaker.logger import logger


# ── Schema ─────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS tools (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    namespace   TEXT DEFAULT 'default',
    base_url    TEXT DEFAULT '',
    schema_json TEXT NOT NULL,
    source_file TEXT,
    class_name  TEXT,
    method_name TEXT,
    is_rest     INTEGER DEFAULT 0,
    embedding   BLOB,
    method_hash TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name);
CREATE INDEX IF NOT EXISTS idx_tools_class ON tools(class_name);
CREATE INDEX IF NOT EXISTS idx_tools_namespace ON tools(namespace);
CREATE INDEX IF NOT EXISTS idx_tools_hash ON tools(method_hash);
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
            # Automatic migration for existing DBs
            try:
                conn.execute("ALTER TABLE tools ADD COLUMN namespace TEXT DEFAULT 'default';")
                conn.execute("ALTER TABLE tools ADD COLUMN base_url TEXT DEFAULT '';")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_namespace ON tools(namespace);")
            except sqlite3.OperationalError:
                pass  # Columns already exist

            try:
                conn.execute("ALTER TABLE tools ADD COLUMN method_hash TEXT;")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_hash ON tools(method_hash);")
            except sqlite3.OperationalError:
                pass

    # ── Write ──────────────────────────────────────────────────────────────
    
    def delete_namespace(self, namespace: str) -> None:
        """Delete all tools for the given namespace."""
        logger.info(f"Deleting namespace '{namespace}' from registry")
        with self._connect() as conn:
            conn.execute("DELETE FROM tools WHERE namespace = ?", (namespace,))

    def upsert_tool(
        self,
        schema: dict,
        namespace: str = "default",
        base_url: str = "",
        source_file: str = "",
        class_name: str = "",
        method_name: str = "",
        is_rest: bool = False,
        embedding: list[float] | None = None,
        method_hash: str | None = None,
    ) -> str:
        """Insert or replace a tool record. Returns the tool ID."""
        import hashlib
        func = schema.get("function", {})
        name = func.get("name", "unknown")
        description = func.get("description", "")
        
        # Deterministic ID based on namespace + name so it updates on conflict
        tool_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"dtgs://{namespace}/{name}"))

        emb_blob = _pack_embedding(embedding) if embedding else None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tools
                    (id, name, description, namespace, base_url, schema_json,
                     source_file, class_name, method_name, is_rest, embedding, method_hash)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    namespace=excluded.namespace,
                    base_url=excluded.base_url,
                    schema_json=excluded.schema_json,
                    embedding=excluded.embedding,
                    method_hash=excluded.method_hash
                """,
                (
                    tool_id, name, description, namespace, base_url, json.dumps(schema),
                    source_file, class_name, method_name,
                    int(is_rest), emb_blob, method_hash
                ),
            )
        logger.debug(f"Upserted tool '{name}' into namespace '{namespace}' (id: {tool_id})")
        return tool_id


    def upsert_many(
        self,
        schemas: list[dict],
        namespace: str = "default",
        base_url: str = "",
        embeddings: list[list[float]] | None = None,
        method_meta: list[dict] | None = None,
    ) -> list[str]:
        """
        Bulk upsert list of schemas.

        Args:
            schemas:     list of ToolSchema dicts
            namespace:   multi-tenant namespace
            base_url:    target API base URL
            embeddings:  optional parallel list of embedding vectors
            method_meta: optional parallel list of dicts (source_file, class_name, etc.)
        """
        ids: list[str] = []
        for i, schema in enumerate(schemas):
            emb = embeddings[i] if embeddings and i < len(embeddings) else None
            meta = method_meta[i] if method_meta and i < len(method_meta) else {}
            tid = self.upsert_tool(
                schema=schema,
                namespace=namespace,
                base_url=base_url,
                source_file=meta.get("source_file", ""),
                class_name=meta.get("class_name", ""),
                method_name=meta.get("method_name", ""),
                is_rest=meta.get("is_rest", False),
                embedding=emb,
                method_hash=meta.get("method_hash", None),
            )
            ids.append(tid)
        logger.info(f"Bulk upserted {len(ids)} tools into namespace '{namespace}'")
        return ids


    # ── Read ───────────────────────────────────────────────────────────────

    def keyword_search(self, query: str, namespace: str = "default", top_k: int = 10) -> list[dict]:
        """LIKE search on name + description for a specific namespace."""
        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT schema_json FROM tools
                WHERE namespace = ? AND (name LIKE ? OR description LIKE ?)
                LIMIT ?
                """,
                (namespace, pattern, pattern, top_k),
            ).fetchall()
        return [json.loads(r["schema_json"]) for r in rows]


    def semantic_search(
        self, query_embedding: list[float], namespace: str = "default", top_k: int = 10
    ) -> list[dict]:
        """Cosine similarity search over stored embeddings for a specific namespace."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT schema_json, embedding FROM tools WHERE namespace = ? AND embedding IS NOT NULL",
                (namespace,)
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
        namespace: str = "default",
        query_embedding: list[float] | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """Unified search: semantic if embedding provided, else keyword. Filters by namespace."""
        if query_embedding:
            return self.semantic_search(query_embedding, namespace, top_k)
        return self.keyword_search(query, namespace, top_k)


    def get_all(self, namespace: str = "default", limit: int = 500) -> list[dict]:
        """Return all stored tool schemas for a specific namespace."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT schema_json FROM tools WHERE namespace = ? LIMIT ?",
                (namespace, limit)
            ).fetchall()
        return [json.loads(r["schema_json"]) for r in rows]

    def get_rest_tools(self, namespace: str = "default", limit: int = 500) -> list[dict]:
        """Return only REST-annotated tool schemas (is_rest=1) for a namespace."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT schema_json FROM tools WHERE namespace = ? AND is_rest = 1 LIMIT ?",
                (namespace, limit)
            ).fetchall()
        return [json.loads(r["schema_json"]) for r in rows]

    def get_controller_groups(self, namespace: str = "default") -> list[dict]:
        """
        Group REST tools by class_name and return controller-level summaries.

        Returns:
            [
                {
                    "class_name": "PaymentController",
                    "api_count": 18,
                    "tool_names": "processPayment, refundPayment, ..."
                },
                ...
            ]
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT class_name, COUNT(*) as api_count,
                       GROUP_CONCAT(name, ', ') as tool_names
                FROM tools
                WHERE namespace = ? AND is_rest = 1 AND class_name != ''
                GROUP BY class_name
                ORDER BY class_name
                """,
                (namespace,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_tools_by_class(self, namespace: str, class_name: str) -> list[dict]:
        """Load tool schemas for a single controller class."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT schema_json FROM tools WHERE namespace = ? AND class_name = ? AND is_rest = 1",
                (namespace, class_name)
            ).fetchall()
        return [json.loads(r["schema_json"]) for r in rows]

    def count(self, namespace: str | None = None) -> int:
        with self._connect() as conn:
            if namespace:
                return conn.execute("SELECT COUNT(*) FROM tools WHERE namespace = ?", (namespace,)).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]

    def list_namespaces(self) -> list[dict]:
        """Return a list of all namespaces with their tool counts and latest creation date."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT namespace, COUNT(*) as count, MAX(created_at) as last_updated, MAX(base_url) as base_url "
                "FROM tools GROUP BY namespace ORDER BY namespace"
            ).fetchall()
        return [dict(r) for r in rows]
