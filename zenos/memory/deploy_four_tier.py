#!/usr/bin/env python3
"""
ZenOS Four-Tier Memory Deployment Script
Initializes all 4 tiers and runs integration tests.
"""
import sys
import time

def test_redis():
    """Test Tier 1: Redis connection"""
    import redis as redis_lib
    from zenos.memory.four_tier_config import REDIS_CONFIG

    print("═══ Tier 1: Redis ═══")
    try:
        r = redis_lib.Redis(**REDIS_CONFIG)
        r.ping()
        print(f"  ✓ Connected to Redis at {REDIS_CONFIG['host']}:{REDIS_CONFIG['port']}")

        # Test basic operations
        r.set("zenos:test", "hello_four_tier", ex=60)
        val = r.get("zenos:test")
        print(f"  ✓ Read/Write: {val}")

        # Test pub/sub
        pubsub = r.pubsub()
        pubsub.subscribe("zenos:events")
        print(f"  ✓ Pub/Sub channel subscribed")

        # Test counters
        r.incr("zenos:counter")
        print(f"  ✓ Counter increment")

        r.close()
        return True
    except Exception as e:
        print(f"  ✗ Redis error: {e}")
        return False


def test_postgres():
    """Test Tier 2: PostgreSQL connection and schema"""
    import psycopg2
    from zenos.memory.four_tier_config import POSTGRES_CONFIG

    print("\n═══ Tier 2: PostgreSQL ═══")
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        conn.autocommit = True
        cur = conn.cursor()
        print(f"  ✓ Connected to PostgreSQL at {POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}")

        # Create tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS zenos_episodes (
                id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                episode_type TEXT DEFAULT 'general',
                importance REAL DEFAULT 0.5,
                tags TEXT[] DEFAULT '{}',
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        print("  ✓ Episodes table ready")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS zenos_tool_log (
                id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                params JSONB DEFAULT '{}',
                result JSONB DEFAULT '{}',
                duration_ms REAL,
                success BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        print("  ✓ Tool log table ready")

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_episodes_session ON zenos_episodes(session_id);
            CREATE INDEX IF NOT EXISTS idx_episodes_tags ON zenos_episodes USING GIN(tags);
            CREATE INDEX IF NOT EXISTS idx_episodes_content ON zenos_episodes USING GIN(to_tsvector('english', content));
            CREATE INDEX IF NOT EXISTS idx_tool_log_session ON zenos_tool_log(session_id);
        """)
        print("  ✓ Indexes created")

        # Test insert
        cur.execute(
            "INSERT INTO zenos_episodes (session_id, content, episode_type, importance) VALUES (%s, %s, %s, %s) RETURNING id",
            ("test-session", "Four-tier memory deployment test", "system", 1.0)
        )
        row_id = cur.fetchone()[0]
        print(f"  ✓ Test episode inserted (id={row_id})")

        # Test full-text search
        cur.execute(
            "SELECT id, content FROM zenos_episodes WHERE to_tsvector('english', content) @@ to_tsquery('english', 'deployment')"
        )
        results = cur.fetchall()
        print(f"  ✓ Full-text search: {len(results)} results")

        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  ✗ PostgreSQL error: {e}")
        return False


def test_qdrant():
    """Test Tier 3: Qdrant connection and collection"""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    from zenos.memory.four_tier_config import QDRANT_CONFIG

    print("\n═══ Tier 3: Qdrant ═══")
    try:
        client = QdrantClient(
            host=QDRANT_CONFIG["host"],
            port=QDRANT_CONFIG["port"],
            api_key=QDRANT_CONFIG["api_key"],
            https=QDRANT_CONFIG["https"],
        )
        print(f"  ✓ Connected to Qdrant at {QDRANT_CONFIG['host']}:{QDRANT_CONFIG['port']}")

        # Create collection
        collection_name = "zenos_semantic"
        collections = [c.name for c in client.get_collections().collections]
        if collection_name not in collections:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )
            print(f"  ✓ Collection '{collection_name}' created (384d, cosine)")
        else:
            print(f"  ✓ Collection '{collection_name}' already exists")

        # Test upsert
        import numpy as np
        test_vector = np.random.rand(384).tolist()
        client.upsert(
            collection_name=collection_name,
            points=[{
                "id": 1,
                "vector": test_vector,
                "payload": {"text": "Four-tier memory test", "source": "deployment"}
            }],
        )
        print("  ✓ Test vector upserted")

        # Test search
        results = client.search(
            collection_name=collection_name,
            query_vector=test_vector,
            limit=3,
        )
        print(f"  ✓ Vector search: {len(results)} results")

        client.close()
        return True
    except Exception as e:
        print(f"  ✗ Qdrant error: {e}")
        return False


def test_minio():
    """Test Tier 4: MinIO (S3) connection"""
    import boto3
    from zenos.memory.four_tier_config import S3_CONFIG

    print("\n═══ Tier 4: MinIO (S3) ═══")
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=S3_CONFIG["endpoint_url"],
            aws_access_key_id=S3_CONFIG["aws_access_key_id"],
            aws_secret_access_key=S3_CONFIG["aws_secret_access_key"],
            region_name=S3_CONFIG["region_name"],
        )
        print(f"  ✓ Connected to MinIO at {S3_CONFIG['endpoint_url']}")

        # Create bucket
        bucket = S3_CONFIG["bucket"]
        try:
            s3.create_bucket(Bucket=bucket)
            print(f"  ✓ Bucket '{bucket}' created")
        except s3.exceptions.BucketAlreadyOwnedByYou:
            print(f"  ✓ Bucket '{bucket}' already exists")

        # Test put
        import json
        test_data = json.dumps({"test": "four-tier memory", "timestamp": time.time()})
        s3.put_object(Bucket=bucket, Key="test/deployment.json", Body=test_data)
        print("  ✓ Test object uploaded")

        # Test get
        obj = s3.get_object(Bucket=bucket, Key="test/deployment.json")
        body = obj["Body"].read().decode()
        print(f"  ✓ Test object retrieved: {len(body)} bytes")

        return True
    except Exception as e:
        print(f"  ✗ MinIO error: {e}")
        return False


def test_four_tier_manager():
    """Test unified FourTierMemoryManager"""
    from zenos.memory.four_tier import FourTierMemoryManager, TieredMemoryConfig

    print("\n═══ FourTierMemoryManager Integration ═══")
    try:
        config = TieredMemoryConfig(
            redis_url="redis://127.0.0.1:6379/0",
            postgres_dsn="postgresql://zenos:zenos@127.0.0.1:5432/zenos",
            qdrant_url="http://127.0.0.1:6333",
            qdrant_api_key="qdrant_hermes_2026_secure_key",
            s3_endpoint="http://127.0.0.1:9000",
            s3_access_key="zenos",
            s3_secret_key="zenos-secret",
            s3_bucket="zenos-cold",
        )
        mgr = FourTierMemoryManager(config)
        print("  ✓ FourTierMemoryManager initialized")

        # Test write to all tiers
        mgr.write(session_id="deploy-test", content="Four-tier memory deployment verified", importance=1.0)
        print("  ✓ Write to all 4 tiers")

        # Test read
        results = mgr.read(session_id="deploy-test", limit=5)
        print(f"  ✓ Read back: {len(results)} results")

        return True
    except Exception as e:
        print(f"  ✗ FourTierMemoryManager error: {e}")
        return False


if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════╗")
    print("║     ZenOS Four-Tier Memory Deployment Test       ║")
    print("╚══════════════════════════════════════════════════╝\n")

    results = []
    results.append(("Redis (Tier 1)", test_redis()))
    time.sleep(0.5)
    results.append(("PostgreSQL (Tier 2)", test_postgres()))
    time.sleep(0.5)
    results.append(("Qdrant (Tier 3)", test_qdrant()))
    time.sleep(0.5)
    results.append(("MinIO (Tier 4)", test_minio()))
    time.sleep(0.5)
    results.append(("FourTierManager", test_four_tier_manager()))

    print("\n╔══════════════════════════════════════════════════╗")
    print("║                  RESULTS                         ║")
    print("╠══════════════════════════════════════════════════╣")
    all_ok = True
    for name, ok in results:
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"║  {status}  {name:<38} ║")
        if not ok:
            all_ok = False
    print("╚══════════════════════════════════════════════════╝")

    if all_ok:
        print("\n🎉 All four tiers operational!")
        sys.exit(0)
    else:
        print("\n⚠️ Some tiers failed. Check logs above.")
        sys.exit(1)
