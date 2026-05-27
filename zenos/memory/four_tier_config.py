"""
ZenOS Four-Tier Memory — Connection Configuration
Auto-generated for aote-hk-cn2 deployment
"""
import os

# ── Tier 1: Redis ──
REDIS_CONFIG = {
    "host": os.getenv("REDIS_HOST", "127.0.0.1"),
    "port": int(os.getenv("REDIS_PORT", "6379")),
    "db": int(os.getenv("REDIS_DB", "0")),
    "decode_responses": True,
}

# ── Tier 2: PostgreSQL ──
POSTGRES_CONFIG = {
    "host": os.getenv("PG_HOST", "127.0.0.1"),
    "port": int(os.getenv("PG_PORT", "5432")),
    "dbname": os.getenv("PG_DATABASE", "zenos"),
    "user": os.getenv("PG_USER", "zenos"),
    "password": os.getenv("PG_PASSWORD", "zenos"),
}

# ── Tier 3: Qdrant ──
QDRANT_CONFIG = {
    "host": os.getenv("QDRANT_HOST", "127.0.0.1"),
    "port": int(os.getenv("QDRANT_PORT", "6333")),
    "api_key": os.getenv("QDRANT_API_KEY", "qdrant_hermes_2026_secure_key"),
    "https": False,
}

# ── Tier 4: MinIO (S3-compatible) ──
S3_CONFIG = {
    "endpoint_url": os.getenv("S3_ENDPOINT", "http://127.0.0.1:9000"),
    "aws_access_key_id": os.getenv("S3_ACCESS_KEY", "zenos"),
    "aws_secret_access_key": os.getenv("S3_SECRET_KEY", "zenos-secret"),
    "region_name": os.getenv("S3_REGION", "us-east-1"),
    "bucket": os.getenv("S3_BUCKET", "zenos-cold"),
}
