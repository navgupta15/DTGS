"""
DTGS SDK — Local Semantic & Keyword Search.

Provides client-side tool filtering so the SDK can select the most relevant
tools per query WITHOUT making additional calls to the DTGS server.

If ``sentence-transformers`` is installed, uses local embeddings for semantic
search. Otherwise, falls back to keyword matching.
"""
from __future__ import annotations

import math
import re
from typing import Any


def _tool_text(tool: dict) -> str:
    """Extract searchable text from a tool schema."""
    func = tool.get("function", {})
    name = func.get("name", "")
    desc = func.get("description", "")
    # Include parameter names for better matching
    params = func.get("parameters", {}).get("properties", {})
    param_names = " ".join(params.keys())
    return f"{name} {desc} {param_names}"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class LocalToolSearch:
    """
    Local tool search engine for client-side filtering.

    Tries to use ``sentence-transformers`` for semantic search. If not
    installed, falls back to keyword-based scoring.

    Args:
        tools: List of tool dicts in OpenAI function-calling format.
        model_name: Sentence-transformer model name for semantic search.
    """

    def __init__(
        self,
        tools: list[dict],
        model_name: str = "all-MiniLM-L6-v2",
    ) -> None:
        self.tools = tools
        self._texts = [_tool_text(t) for t in tools]
        self._model: Any = None
        self._embeddings: Any = None
        self._has_semantic = False

        self._init_embeddings(model_name)

    def _init_embeddings(self, model_name: str) -> None:
        """Try to load sentence-transformers for semantic search."""
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model_name)
            self._embeddings = self._model.encode(self._texts)
            self._has_semantic = True
        except ImportError:
            # sentence-transformers not installed — use keyword fallback
            pass
        except Exception:
            # Model loading failed — use keyword fallback
            pass

    @property
    def has_semantic_search(self) -> bool:
        """Whether semantic search is available."""
        return self._has_semantic

    def search(self, query: str, top_k: int = 15) -> list[dict]:
        """
        Return the top-K most relevant tools for the given query.

        Uses semantic search if sentence-transformers is installed,
        otherwise falls back to keyword matching.

        Args:
            query: Natural language query string.
            top_k: Maximum number of tools to return.

        Returns:
            List of tool dicts (filtered and ranked by relevance).
        """
        if self._has_semantic:
            return self._semantic_search(query, top_k)
        return self._keyword_search(query, top_k)

    def _semantic_search(self, query: str, top_k: int) -> list[dict]:
        """Cosine similarity search using local embeddings."""
        query_embedding = self._model.encode(query)

        scored: list[tuple[float, int]] = []
        for i, tool_emb in enumerate(self._embeddings):
            score = _cosine_similarity(query_embedding.tolist(), tool_emb.tolist())
            scored.append((score, i))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [self.tools[idx] for _, idx in scored[:top_k]]

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """
        Simple keyword matching fallback.

        Scores each tool based on how many query words appear in its
        name, description, and parameter names.
        """
        # Tokenize query into lowercase words
        query_words = set(re.findall(r"\w+", query.lower()))
        if not query_words:
            return self.tools[:top_k]

        scored: list[tuple[float, int]] = []
        for i, text in enumerate(self._texts):
            text_lower = text.lower()
            # Count matching words
            matches = sum(1 for word in query_words if word in text_lower)
            if matches > 0:
                # Normalize by query length for fair scoring
                score = matches / len(query_words)
                scored.append((score, i))

        if not scored:
            # No keyword matches — return first top_k tools as fallback
            return self.tools[:top_k]

        scored.sort(key=lambda x: x[0], reverse=True)
        return [self.tools[idx] for _, idx in scored[:top_k]]
