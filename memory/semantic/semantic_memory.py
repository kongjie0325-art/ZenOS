"""ZenOS Semantic Memory - 语义知识层

基于 Qdrant 向量数据库
保存：历史总结、长期知识、文档、项目结构、经验
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional


@dataclass
class MemoryItem:
    """记忆条目"""
    content: str
    category: str = "general"
    metadata: dict[str, Any] | None = None
    embedding: list[float] | None = None
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "category": self.category,
            "metadata": self.metadata or {},
            "score": self.score,
        }


from dataclasses import dataclass


# Embedding function type
EmbeddingFn = callable


class SemanticMemory:
    """语义记忆（向量知识库）"""

    COLLECTION_NAME = "zenos_memories"

    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        api_key: str | None = None,
        embedding_fn: Any = None,
        vector_size: int = 384,
    ):
        self._qdrant_url = qdrant_url
        self._api_key = api_key
        self._embedding_fn = embedding_fn
        self._vector_size = vector_size
        self._client = None
        self._local: list[MemoryItem] = []

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http.models import Distance, VectorParams

            self._client = QdrantClient(url=qdrant_url, api_key=api_key)
            # Ensure collection exists
            collections = [c.name for c in self._client.get_collections().collections]
            if self.COLLECTION_NAME not in collections:
                self._client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
        except Exception:
            self._client = None

    def _embed(self, text: str) -> list[float]:
        """获取 embedding"""
        if self._embedding_fn:
            return self._embedding_fn(text)
        # Fallback: simple hash-based pseudo embedding
        h = hashlib.md5(text.encode()).hexdigest()
        return [int(h[i:i+2], 16) / 255.0 for i in range(0, min(len(h), self._vector_size * 2), 2)][:self._vector_size]

    def store(
        self,
        content: str,
        category: str = "general",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """存储记忆"""
        item = MemoryItem(content=content, category=category, metadata=metadata)

        if self._client:
            try:
                from qdrant_client.http.models import PointStruct
                import uuid

                embedding = self._embed(content)
                point_id = str(uuid.uuid4())
                self._client.upsert(
                    collection_name=self.COLLECTION_NAME,
                    points=[
                        PointStruct(
                            id=point_id,
                            vector=embedding,
                            payload={"content": content, "category": category, "metadata": metadata or {}},
                        )
                    ],
                )
                return point_id
            except Exception:
                pass

        self._local.append(item)
        return f"local_{len(self._local)}"

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 5,
        min_score: float = 0.3,
    ) -> list[MemoryItem]:
        """语义搜索"""
        results: list[MemoryItem] = []

        if self._client:
            try:
                from qdrant_client.http.models import Filter, FieldCondition, MatchValue

                query_vector = self._embed(query)
                query_filter = None
                if category:
                    query_filter = Filter(
                        must=[FieldCondition(key="category", match=MatchValue(value=category))]
                    )

                search_results = self._client.search(
                    collection_name=self.COLLECTION_NAME,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    score_threshold=min_score,
                )

                for hit in search_results:
                    payload = hit.payload
                    results.append(MemoryItem(
                        content=payload.get("content", ""),
                        category=payload.get("category", "general"),
                        metadata=payload.get("metadata", {}),
                        score=hit.score,
                    ))
                return results
            except Exception:
                pass

        # Fallback: local keyword search
        query_lower = query.lower()
        for item in self._local:
            if category and item.category != category:
                continue
            score = sum(1 for word in query_lower.split() if word in item.content.lower()) / max(len(query_lower.split()), 1)
            if score >= min_score:
                item.score = score
                results.append(item)

        results.sort(key=lambda x: -x.score)
        return results[:limit]

    def get_categories(self) -> list[str]:
        """获取所有分类"""
        if self._client:
            try:
                result = self._client.scroll(
                    collection_name=self.COLLECTION_NAME,
                    limit=1000,
                    with_payload=["category"],
                )
                categories = set()
                for point in result[0]:
                    cat = point.payload.get("category", "general")
                    categories.add(cat)
                return sorted(categories)
            except Exception:
                pass

        return sorted(set(item.category for item in self._local))

    def count(self) -> int:
        if self._client:
            try:
                info = self._client.get_collection(self.COLLECTION_NAME)
                return info.points_count
            except Exception:
                pass
        return len(self._local)
