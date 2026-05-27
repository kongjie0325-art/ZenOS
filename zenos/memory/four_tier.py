"""
Four-Tier Memory Storage Architecture

Tier 1: Redis      — Working Memory (hot cache, session state, real-time)
Tier 2: PostgreSQL  — Episodic Memory (structured experiences, temporal, queryable)
Tier 3: Qdrant      — Semantic Memory (vector search, similarity, embeddings)
Tier 4: S3/R2       — Cold Storage (backups, archives, large objects)

Data Flow:
  Agent Action → Redis (immediate) → PG (persist) → Qdrant (embed) → S3 (archive)
  
Retrieval Flow:
  Query → Redis (check cache) → PG (structured query) → Qdrant (vector search) → Merge & Rank
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Tier 1: Redis — Working Memory (Hot Cache)
# ═══════════════════════════════════════════════════════════════════

class RedisWorkingMemory:
    """Redis-backed working memory for real-time session data.
    
    Use cases:
    - Session state (current context, active tools)
    - Real-time counters (API rate limits, token usage)
    - Pub/sub for inter-agent communication
    - Temporary computation results
    
    Data model:
    - session:{id}:state  → JSON blob of current session state
    - session:{id}:ctx    → Recent conversation context (list)
    - session:{id}:tools  → Tool call history (sorted set by timestamp)
    - global:counters    → System-wide counters (token usage, API calls)
    - agent:{id}:status   → Agent status (hash)
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0", 
                 default_ttl: int = 3600, key_prefix: str = "zenos"):
        self._url = redis_url
        self._ttl = default_ttl
        self._prefix = key_prefix
        self._client = None

    async def connect(self):
        """Initialize Redis connection."""
        try:
            import redis.asyncio as redis
            self._client = redis.from_url(self._url, decode_responses=True)
            await self._client.ping()
            logger.info("Redis Working Memory connected: %s", self._url)
        except Exception as e:
            logger.error("Redis connection failed: %s", e)
            self._client = None

    def _key(self, *parts) -> str:
        return f"{self._prefix}:" + ":".join(str(p) for p in parts)

    async def set_session_state(self, session_id: str, state: Dict, ttl: int = None) -> bool:
        """Store session state as JSON."""
        if not self._client:
            return False
        try:
            key = self._key("session", session_id, "state")
            await self._client.setex(key, ttl or self._ttl, json.dumps(state))
            return True
        except Exception as e:
            logger.error("Redis set_session_state error: %s", e)
            return False

    async def get_session_state(self, session_id: str) -> Optional[Dict]:
        """Retrieve session state."""
        if not self._client:
            return None
        try:
            key = self._key("session", session_id, "state")
            data = await self._client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error("Redis get_session_state error: %s", e)
            return None

    async def append_context(self, session_id: str, role: str, content: str,
                              max_items: int = 50) -> bool:
        """Append message to session context list."""
        if not self._client:
            return False
        try:
            key = self._key("session", session_id, "ctx")
            msg = json.dumps({"role": role, "content": content, "ts": time.time()})
            pipe = self._client.pipeline()
            pipe.rpush(key, msg)
            pipe.ltrim(key, -max_items, -1)
            pipe.expire(key, self._ttl)
            await pipe.execute()
            return True
        except Exception as e:
            logger.error("Redis append_context error: %s", e)
            return False

    async def get_context(self, session_id: str, last_n: int = 20) -> List[Dict]:
        """Get recent context messages."""
        if not self._client:
            return []
        try:
            key = self._key("session", session_id, "ctx")
            items = await self._client.lrange(key, -last_n, -1)
            return [json.loads(item) for item in items]
        except Exception as e:
            logger.error("Redis get_context error: %s", e)
            return []

    async def record_tool_call(self, session_id: str, tool_name: str,
                                params: Dict, result: Any, duration_ms: float) -> bool:
        """Record a tool call in the session history."""
        if not self._client:
            return False
        try:
            key = self._key("session", session_id, "tools")
            entry = json.dumps({
                "tool": tool_name,
                "params": str(params)[:200],
                "result": str(result)[:200],
                "duration_ms": duration_ms,
                "ts": time.time(),
            })
            await self._client.zadd(key, {entry: time.time()})
            await self._client.expire(key, self._ttl)
            return True
        except Exception as e:
            logger.error("Redis record_tool_call error: %s", e)
            return False

    async def increment_counter(self, name: str, amount: int = 1) -> int:
        """Atomic counter increment."""
        if not self._client:
            return 0
        try:
            key = self._key("global", "counters", name)
            return await self._client.incrby(key, amount)
        except Exception as e:
            logger.error("Redis increment_counter error: %s", e)
            return 0

    async def set_agent_status(self, agent_id: str, status: str, **extra) -> bool:
        """Update agent status hash."""
        if not self._client:
            return False
        try:
            key = self._key("agent", agent_id, "status")
            data = {"status": status, "updated_at": time.time(), **extra}
            await self._client.hset(key, mapping={k: str(v) for k, v in data.items()})
            await self._client.expire(key, self._ttl)
            return True
        except Exception as e:
            logger.error("Redis set_agent_status error: %s", e)
            return False

    async def publish(self, channel: str, message: Dict) -> int:
        """Publish message to a Redis pub/sub channel."""
        if not self._client:
            return 0
        try:
            return await self._client.publish(f"{self._prefix}:channel:{channel}", json.dumps(message))
        except Exception as e:
            logger.error("Redis publish error: %s", e)
            return 0

    async def close(self):
        if self._client:
            await self._client.close()


# ═══════════════════════════════════════════════════════════════════
# Tier 2: PostgreSQL — Episodic Memory (Structured Experiences)
# ═══════════════════════════════════════════════════════════════════

# SQL schema for PostgreSQL episodic memory
EPISODIC_SCHEMA = """
-- Episodic memories: structured experiences with temporal indexing
CREATE TABLE IF NOT EXISTS episodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      TEXT NOT NULL,
    agent_id        TEXT,
    content         TEXT NOT NULL,
    importance      REAL DEFAULT 0.5,
    emotion         TEXT,           -- emotional context: positive/negative/neutral
    outcome         TEXT,           -- success/failure/partial
    metadata        JSONB DEFAULT '{}',
    embedding_id    TEXT,           -- reference to Qdrant vector
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id);
CREATE INDEX IF NOT EXISTS idx_episodes_agent ON episodes(agent_id);
CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_importance ON episodes(importance DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_metadata ON episodes USING GIN(metadata);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_episodes_fts ON episodes 
    USING GIN(to_tsvector('english', content));

-- Tool call log
CREATE TABLE IF NOT EXISTS tool_calls (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      TEXT NOT NULL,
    agent_id        TEXT,
    tool_name       TEXT NOT NULL,
    params          JSONB DEFAULT '{}',
    result          JSONB,
    duration_ms     REAL,
    success         BOOLEAN DEFAULT TRUE,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool ON tool_calls(tool_name);

-- Memory tags for categorization
CREATE TABLE IF NOT EXISTS memory_tags (
    episode_id      UUID REFERENCES episodes(id) ON DELETE CASCADE,
    tag             TEXT NOT NULL,
    confidence      REAL DEFAULT 1.0,
    PRIMARY KEY (episode_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_memory_tags_tag ON memory_tags(tag);

-- Session summaries (compressed episodic memory)
CREATE TABLE IF NOT EXISTS session_summaries (
    session_id      TEXT PRIMARY KEY,
    agent_id        TEXT,
    summary         TEXT NOT NULL,
    key_events      JSONB DEFAULT '[]',
    episode_count   INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
"""

@dataclass
class EpisodeRecord:
    """A single episodic memory record for PostgreSQL."""
    content: str
    session_id: str = ""
    agent_id: str = ""
    importance: float = 0.5
    emotion: str = "neutral"
    outcome: str = "unknown"
    metadata: Dict = field(default_factory=dict)
    embedding_id: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)


class PostgreEpisodicMemory:
    """PostgreSQL-backed episodic memory for structured experience storage.
    
    Use cases:
    - Persistent experience log with complex querying
    - Temporal range queries ("what happened between X and Y?")
    - Full-text search over past experiences
    - Emotional context and outcome tracking
    - Tool call history with structured params/results
    
    Data model:
    - episodes: Main experience records with metadata + full-text search
    - tool_calls: Structured tool call log
    - memory_tags: Categorization tags for episodes
    - session_summaries: Compressed session summaries
    """

    def __init__(self, dsn: str = "postgresql://zenos:zenos@localhost:5432/zenos"):
        self._dsn = dsn
        self._pool = None

    async def connect(self):
        """Initialize PostgreSQL connection pool."""
        try:
            import asyncpg
            self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
            async with self._pool.acquire() as conn:
                await conn.execute(EPISODIC_SCHEMA)
            logger.info("PostgreSQL Episodic Memory connected")
        except Exception as e:
            logger.error("PostgreSQL connection failed: %s", e)
            self._pool = None

    async def add_episode(self, episode: EpisodeRecord) -> Optional[str]:
        """Insert a new episodic memory."""
        if not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO episodes (id, session_id, agent_id, content, importance, 
                                          emotion, outcome, metadata, embedding_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id::text
                """, episode.id, episode.session_id, episode.agent_id, episode.content,
                     episode.importance, episode.emotion, episode.outcome,
                     json.dumps(episode.metadata), episode.embedding_id)
                return row['id'] if row else None
        except Exception as e:
            logger.error("PG add_episode error: %s", e)
            return None

    async def search_episodes(self, query: str = None, session_id: str = None,
                               agent_id: str = None, tags: List[str] = None,
                               emotion: str = None, outcome: str = None,
                               since: float = None, until: float = None,
                               min_importance: float = 0.0,
                               limit: int = 20, offset: int = 0) -> List[Dict]:
        """Complex search with multiple filters."""
        if not self._pool:
            return []
        try:
            conditions = ["importance >= $1"]
            params = [min_importance]
            param_idx = 2

            if query:
                conditions.append(f"to_tsvector('english', content) @@ plainto_tsquery('english', ${param_idx})")
                params.append(query)
                param_idx += 1

            if session_id:
                conditions.append(f"session_id = ${param_idx}")
                params.append(session_id)
                param_idx += 1

            if agent_id:
                conditions.append(f"agent_id = ${param_idx}")
                params.append(agent_id)
                param_idx += 1

            if emotion:
                conditions.append(f"emotion = ${param_idx}")
                params.append(emotion)
                param_idx += 1

            if outcome:
                conditions.append(f"outcome = ${param_idx}")
                params.append(outcome)
                param_idx += 1

            if since:
                conditions.append(f"created_at >= to_timestamp(${param_idx})")
                params.append(since)
                param_idx += 1

            if until:
                conditions.append(f"created_at <= to_timestamp(${param_idx})")
                params.append(until)
                param_idx += 1

            if tags:
                conditions.append(f"EXISTS (SELECT 1 FROM memory_tags mt WHERE mt.episode_id = episodes.id AND mt.tag = ANY(${param_idx}))")
                params.append(tags)
                param_idx += 1

            where = " AND ".join(conditions)
            params.extend([limit, offset])

            async with self._pool.acquire() as conn:
                rows = await conn.fetch(f"""
                    SELECT id::text, session_id, agent_id, content, importance,
                           emotion, outcome, metadata, embedding_id, created_at
                    FROM episodes
                    WHERE {where}
                    ORDER BY importance DESC, created_at DESC
                    LIMIT ${param_idx} OFFSET ${param_idx + 1}
                """, *params)

                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("PG search_episodes error: %s", e)
            return []

    async def get_episode_by_id(self, episode_id: str) -> Optional[Dict]:
        if not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM episodes WHERE id::text = $1", episode_id
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error("PG get_episode_by_id error: %s", e)
            return None

    async def update_importance(self, episode_id: str, importance: float) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE episodes SET importance = $1, updated_at = NOW() WHERE id::text = $2",
                    importance, episode_id
                )
                return True
        except Exception as e:
            logger.error("PG update_importance error: %s", e)
            return False

    async def forget_episodes(self, session_id: str = None, before: float = None,
                               min_importance: float = None) -> int:
        """Delete episodes matching criteria."""
        if not self._pool:
            return 0
        try:
            conditions = []
            params = []
            idx = 1
            if session_id:
                conditions.append(f"session_id = ${idx}")
                params.append(session_id)
                idx += 1
            if before:
                conditions.append(f"created_at < to_timestamp(${idx})")
                params.append(before)
                idx += 1
            if min_importance is not None:
                conditions.append(f"importance < ${idx}")
                params.append(min_importance)
                idx += 1

            if not conditions:
                return 0

            where = " AND ".join(conditions)
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    f"DELETE FROM episodes WHERE {where}", *params
                )
                return int(result.split()[-1])  # extract count from "DELETE N"
        except Exception as e:
            logger.error("PG forget_episodes error: %s", e)
            return 0

    async def add_tag(self, episode_id: str, tag: str, confidence: float = 1.0) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO memory_tags (episode_id, tag, confidence)
                    VALUES ($1::uuid, $2, $3)
                    ON CONFLICT DO NOTHING
                """, episode_id, tag, confidence)
                return True
        except Exception as e:
            logger.error("PG add_tag error: %s", e)
            return False

    async def log_tool_call(self, session_id: str, tool_name: str, params: Dict,
                             result: Any, duration_ms: float, success: bool = True,
                             error: str = None, agent_id: str = None) -> bool:
        """Log a structured tool call."""
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO tool_calls (session_id, agent_id, tool_name, params, result, duration_ms, success, error)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, session_id, agent_id, tool_name, json.dumps(params)[:1000],
                     json.dumps(result)[:1000] if result else None,
                     duration_ms, success, error)
                return True
        except Exception as e:
            logger.error("PG log_tool_call error: %s", e)
            return False

    async def get_stats(self) -> Dict[str, int]:
        if not self._pool:
            return {}
        try:
            async with self._pool.acquire() as conn:
                episodes = await conn.fetchrow("SELECT COUNT(*) as n FROM episodes")
                tool_calls = await conn.fetchrow("SELECT COUNT(*) as n FROM tool_calls")
                tags = await conn.fetchrow("SELECT COUNT(DISTINCT tag) as n FROM memory_tags")
                return {
                    'episodes': episodes['n'],
                    'tool_calls': tool_calls['n'],
                    'unique_tags': tags['n'],
                }
        except Exception:
            return {}

    async def close(self):
        if self._pool:
            await self._pool.close()


# ═══════════════════════════════════════════════════════════════════
# Tier 3: Qdrant — Semantic Memory (Vector Search)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class VectorRecord:
    """A vector record for Qdrant."""
    id: str
    vector: List[float]
    payload: Dict[str, Any] = field(default_factory=dict)


class QdrantSemanticMemory:
    """Qdrant-backed semantic memory for vector similarity search.
    
    Use cases:
    - Semantic search over knowledge base
    - Find similar past experiences
    - Context-aware retrieval ("find memories related to X")
    - Embedding-based clustering
    
    Data model:
    - Collection: "zenos_semantic" — Knowledge items with embeddings
    - Collection: "zenos_episodes" — Episode embeddings for similarity
    """

    def __init__(self, url: str = "http://localhost:6333", 
                 collection: str = "zenos_semantic",
                 vector_size: int = 1536,
                 api_key: str = None):
        self._url = url
        self._collection = collection
        self._vector_size = vector_size
        self._api_key = api_key
        self._client = None

    async def connect(self):
        """Initialize Qdrant client and ensure collection exists."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams, PointStruct
            
            self._client = QdrantClient(url=self._url, api_key=self._api_key)
            
            # Create collection if not exists
            collections = [c.name for c in self._client.get_collections().collections]
            if self._collection not in collections:
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(
                        size=self._vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                # Create payload indexes for common filters
                self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name="session_id",
                    field_type="keyword",
                )
                self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name="importance",
                    field_type="float",
                )
                logger.info("Qdrant collection '%s' created", self._collection)
            
            logger.info("Qdrant Semantic Memory connected: %s", self._url)
        except Exception as e:
            logger.error("Qdrant connection failed: %s", e)
            self._client = None

    async def upsert(self, record: VectorRecord) -> bool:
        """Insert or update a vector."""
        if not self._client:
            return False
        try:
            from qdrant_client.models import PointStruct
            self._client.upsert(
                collection_name=self._collection,
                points=[PointStruct(
                    id=record.id,
                    vector=record.vector,
                    payload=record.payload,
                )],
            )
            return True
        except Exception as e:
            logger.error("Qdrant upsert error: %s", e)
            return False

    async def search(self, query_vector: List[float], limit: int = 10,
                      min_score: float = 0.0,
                      filters: Dict[str, Any] = None) -> List[Dict]:
        """Vector similarity search with optional filters."""
        if not self._client:
            return []
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            
            qdrant_filter = None
            if filters:
                conditions = []
                for key, value in filters.items():
                    if isinstance(value, list):
                        conditions.append(FieldCondition(key=key, match=MatchValue(any=value)))
                    else:
                        conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
                if conditions:
                    qdrant_filter = Filter(must=conditions)

            results = self._client.query_points(
                collection_name=self._collection,
                query=query_vector,
                limit=limit,
                score_threshold=min_score,
                query_filter=qdrant_filter,
                with_payload=True,
            )
            
            return [
                {
                    'id': str(r.id),
                    'score': r.score,
                    'payload': r.payload,
                }
                for r in results.points
            ]
        except Exception as e:
            logger.error("Qdrant search error: %s", e)
            return []

    async def delete(self, id: str) -> bool:
        if not self._client:
            return False
        try:
            from qdrant_client.models import PointIdsList
            self._client.delete(
                collection_name=self._collection,
                points_selector=PointIdsList(points=[id]),
            )
            return True
        except Exception as e:
            logger.error("Qdrant delete error: %s", e)
            return False

    async def count(self) -> int:
        if not self._client:
            return 0
        try:
            return self._client.count(collection_name=self._collection).count
        except Exception:
            return 0

    async def close(self):
        if self._client:
            self._client.close()


# ═══════════════════════════════════════════════════════════════════
# Tier 4: S3/R2 — Cold Storage (Backups, Archives)
# ═══════════════════════════════════════════════════════════════════

class S3ColdStorage:
    """S3/R2-backed cold storage for memory backups and archives.
    
    Use cases:
    - Daily/weekly memory backups
    - Large objects (conversation logs, tool outputs)
    - Historical archives (old sessions, deleted memories)
    - Cross-region replication for disaster recovery
    
    Data layout:
    - zenos/backups/episodes/{date}.json.gz
    - zenos/backups/sessions/{session_id}/full.json.gz
    - zenos/archives/{year}/{month}/episodes.json.gz
    - zenos/snapshots/weekly/{date}/
    """

    def __init__(self, endpoint_url: str = None,
                 access_key: str = None, secret_key: str = None,
                 bucket: str = "zenos-memory",
                 region: str = "auto"):
        self._endpoint = endpoint_url
        self._access = access_key
        self._secret = secret_key
        self._bucket = bucket
        self._region = region
        self._client = None

    async def connect(self):
        """Initialize S3/R2 client."""
        try:
            import boto3
            session = boto3.Session(
                aws_access_key_id=self._access,
                aws_secret_access_key=self._secret,
                region_name=self._region,
            )
            kwargs = {}
            if self._endpoint:
                kwargs['endpoint_url'] = self._endpoint
            self._client = session.client('s3', **kwargs)
            
            # Ensure bucket exists
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except Exception:
                self._client.create_bucket(Bucket=self._bucket)
                logger.info("S3 bucket '%s' created", self._bucket)
            
            logger.info("S3 Cold Storage connected: %s/%s", self._endpoint or "aws", self._bucket)
        except Exception as e:
            logger.error("S3 connection failed: %s", e)
            self._client = None

    async def backup_episodes(self, episodes: List[Dict], date: str = None) -> bool:
        """Backup episodes to S3 as compressed JSON."""
        if not self._client:
            return False
        try:
            import gzip
            from datetime import datetime
            date = date or datetime.utcnow().strftime("%Y-%m-%d")
            key = f"zenos/backups/episodes/{date}.json.gz"
            
            data = json.dumps(episodes, default=str).encode('utf-8')
            compressed = gzip.compress(data, compresslevel=6)
            
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=compressed,
                ContentType='application/gzip',
                Metadata={'record_count': str(len(episodes)), 'date': date},
            )
            logger.info("Backed up %d episodes to s3://%s/%s", len(episodes), self._bucket, key)
            return True
        except Exception as e:
            logger.error("S3 backup_episodes error: %s", e)
            return False

    async def backup_session(self, session_id: str, data: Dict) -> bool:
        """Backup a full session to S3."""
        if not self._client:
            return False
        try:
            import gzip
            key = f"zenos/backups/sessions/{session_id}/full.json.gz"
            compressed = gzip.compress(json.dumps(data, default=str).encode('utf-8'))
            self._client.put_object(Bucket=self._bucket, Key=key, Body=compressed)
            return True
        except Exception as e:
            logger.error("S3 backup_session error: %s", e)
            return False

    async def restore_episodes(self, date: str) -> List[Dict]:
        """Restore episodes from S3 backup."""
        if not self._client:
            return []
        try:
            import gzip
            key = f"zenos/backups/episodes/{date}.json.gz"
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            data = gzip.decompress(resp['Body'].read())
            return json.loads(data)
        except Exception as e:
            logger.error("S3 restore_episodes error: %s", e)
            return []

    async def list_backups(self, prefix: str = "zenos/backups/") -> List[Dict]:
        """List available backups."""
        if not self._client:
            return []
        try:
            resp = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
            return [
                {'key': obj['Key'], 'size': obj['Size'], 'modified': obj['LastModified'].isoformat()}
                for obj in resp.get('Contents', [])
            ]
        except Exception as e:
            logger.error("S3 list_backups error: %s", e)
            return []

    async def archive_old_sessions(self, sessions: List[Dict], 
                                    year: int, month: int) -> bool:
        """Archive old session data to cold storage."""
        if not self._client:
            return False
        try:
            import gzip
            key = f"zenos/archives/{year}/{month:02d}/sessions.json.gz"
            compressed = gzip.compress(json.dumps(sessions, default=str).encode('utf-8'))
            self._client.put_object(Bucket=self._bucket, Key=key, Body=compressed)
            return True
        except Exception as e:
            logger.error("S3 archive error: %s", e)
            return False


# ═══════════════════════════════════════════════════════════════════
# Unified Four-Tier Memory Manager
# ═══════════════════════════════════════════════════════════════════

class FourTierMemoryManager:
    """Orchestrates all four memory tiers.
    
    Write path:
      1. Write to Redis (fast, immediate)
      2. Write to PostgreSQL (structured, persistent)
      3. Generate embedding → Write to Qdrant (semantic search)
      4. Periodic backup to S3 (cold storage)
    
    Read path:
      1. Check Redis cache first
      2. Query PostgreSQL for structured matches
      3. Search Qdrant for semantic matches
      4. Merge, deduplicate, rank results
    
    Architecture:
      ┌──────────────────────────────────────────────────────┐
      │                  FourTierMemoryManager                │
      │                                                      │
      │  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌────────┐ │
      │  │  Redis   │  │PostgreSQL│  │ Qdrant │  │  S3    │ │
      │  │ (Tier 1) │  │ (Tier 2) │  │(Tier 3)│  │(Tier 4)│ │
      │  │         │  │          │  │        │  │        │ │
      │  │ Session │  │ Episodes │  │Vectors │  │Backups │ │
      │  │ State   │  │ Tool Log │  │Search  │  │Archive │ │
      │  │ Cache   │  │ Tags     │  │Cluster │  │Snapshot│ │
      │  └────┬────┘  └────┬─────┘  └───┬────┘  └───┬────┘ │
      │       │            │            │            │      │
      │       └────────────┴────────────┴────────────┘      │
      │                       │                             │
      │              Unified Retrieval                      │
      └──────────────────────────────────────────────────────┘
    """

    def __init__(self, config: Dict[str, Any] = None):
        config = config or {}
        self.redis = RedisWorkingMemory(
            redis_url=config.get('redis_url', 'redis://localhost:6379/0'),
            default_ttl=config.get('redis_ttl', 3600),
        )
        self.postgres = PostgreEpisodicMemory(
            dsn=config.get('pg_dsn', 'postgresql://zenos:zenos@localhost:5432/zenos'),
        )
        self.qdrant = QdrantSemanticMemory(
            url=config.get('qdrant_url', 'http://localhost:6333'),
            collection=config.get('qdrant_collection', 'zenos_semantic'),
            vector_size=config.get('vector_size', 1536),
            api_key=config.get('qdrant_api_key'),
        )
        self.s3 = S3ColdStorage(
            endpoint_url=config.get('s3_endpoint'),
            access_key=config.get('s3_access_key'),
            secret_key=config.get('s3_secret_key'),
            bucket=config.get('s3_bucket', 'zenos-memory'),
        )
        self._embedder = None

    async def connect_all(self):
        """Initialize all four tiers."""
        await self.redis.connect()
        await self.postgres.connect()
        await self.qdrant.connect()
        await self.s3.connect()
        logger.info("Four-Tier Memory: all tiers connected")

    async def close_all(self):
        await self.redis.close()
        await self.postgres.close()
        await self.qdrant.close()

    # ── Write path ─────────────────────────────────────────────

    async def remember(self, content: str, session_id: str = "",
                        importance: float = 0.5, emotion: str = "neutral",
                        outcome: str = "unknown", metadata: Dict = None,
                        agent_id: str = "") -> Dict[str, bool]:
        """Write a memory across all tiers."""
        results = {}
        episode_id = str(uuid.uuid4())
        timestamp = time.time()

        # Tier 1: Redis (fast cache)
        try:
            await self.redis.append_context(session_id, "memory", content)
            results['redis'] = True
        except Exception:
            results['redis'] = False

        # Tier 2: PostgreSQL (structured storage)
        try:
            episode = EpisodeRecord(
                id=episode_id, content=content, session_id=session_id,
                agent_id=agent_id, importance=importance, emotion=emotion,
                outcome=outcome, metadata=metadata or {},
            )
            pg_id = await self.postgres.add_episode(episode)
            results['postgres'] = pg_id is not None
        except Exception:
            results['postgres'] = False

        # Tier 3: Qdrant (vector embedding)
        try:
            vector = await self._embed(content)
            if vector:
                await self.qdrant.upsert(VectorRecord(
                    id=episode_id, vector=vector,
                    payload={"content": content, "session_id": session_id,
                             "importance": importance, "created_at": timestamp},
                ))
                results['qdrant'] = True
            else:
                results['qdrant'] = False
        except Exception:
            results['qdrant'] = False

        return results

    # ── Read path ──────────────────────────────────────────────

    async def recall(self, query: str, session_id: str = None,
                      limit: int = 10, strategy: str = "hybrid") -> List[Dict]:
        """Retrieve memories using multi-tier hybrid search."""
        results = []

        # Tier 1: Redis cache check
        try:
            if session_id:
                cached = await self.redis.get_context(session_id, last_n=limit)
                for msg in cached:
                    results.append({
                        'content': msg.get('content', ''),
                        'source': 'redis_cache',
                        'score': 1.0,
                    })
        except Exception:
            pass

        # Tier 2: PostgreSQL structured search
        try:
            pg_results = await self.postgres.search_episodes(
                query=query if strategy in ("hybrid", "keyword") else None,
                session_id=session_id,
                limit=limit,
            )
            for row in pg_results:
                results.append({
                    'id': row.get('id'),
                    'content': row.get('content'),
                    'importance': row.get('importance'),
                    'emotion': row.get('emotion'),
                    'outcome': row.get('outcome'),
                    'created_at': str(row.get('created_at', '')),
                    'source': 'postgres',
                    'score': row.get('importance', 0.5),
                })
        except Exception:
            pass

        # Tier 3: Qdrant vector search
        try:
            if strategy in ("hybrid", "semantic"):
                vector = await self._embed(query)
                if vector:
                    qdrant_result = self.qdrant._client.query_points(
                        collection_name=self.qdrant._collection,
                        query=vector,
                        limit=limit,
                        score_threshold=0.3,
                        with_payload=True,
                    )
                    qdrant_results = qdrant_result.points
                    for r in qdrant_results:
                        results.append({
                            'id': r['id'],
                            'content': r['payload'].get('content', ''),
                            'importance': r['payload'].get('importance', 0.5),
                            'source': 'qdrant',
                            'score': r['score'],
                        })
        except Exception:
            pass

        # Deduplicate and rank
        seen = set()
        unique = []
        for r in results:
            content_hash = hash(r.get('content', '')[:100])
            if content_hash not in seen:
                seen.add(content_hash)
                unique.append(r)

        unique.sort(key=lambda x: x.get('score', 0), reverse=True)
        return unique[:limit]

    # ── Backup path ────────────────────────────────────────────

    async def backup_to_s3(self, date: str = None) -> bool:
        """Backup all episodes from PostgreSQL to S3."""
        try:
            episodes = await self.postgres.search_episodes(limit=100000)
            return await self.s3.backup_episodes(episodes, date)
        except Exception as e:
            logger.error("Backup to S3 failed: %s", e)
            return False

    # ── Embedding helper ───────────────────────────────────────

    async def _embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding vector for text."""
        import numpy as np
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer('all-MiniLM-L6-v2')
            except Exception:
                # Fallback: deterministic hash-based pseudo-embedding
                # Not semantically meaningful, but allows Qdrant to function
                print("  [WARN] sentence_transformers not available, using fallback embedding")
                np.random.seed(hash(text) % 2**32)
                return np.random.rand(self.qdrant._vector_size).tolist()
        try:
            return self._embedder.encode(text).tolist()
        except Exception:
            np.random.seed(hash(text) % 2**32)
            return np.random.rand(self.qdrant._vector_size).tolist()
