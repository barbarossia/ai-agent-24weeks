"""Read-only wrapper around Week 11's executing psycopg store."""

import os

from obsidian_knowledge_agent.config import MockEmbeddingProvider
from obsidian_knowledge_agent.store import PgStore

from .errors import IntegrationBlocked


class Week11Retrieval:
    def __init__(self, top_k=3, source_path=None, tags=None):
        if not 1 <= top_k <= 5:
            raise ValueError("top_k must be 1–5")
        self.top_k = top_k
        self.source_path = source_path
        self.tags = tags or []

    def retrieve(self, question):
        # Require explicit existing configuration; do not discover files or guess a database.
        dsn = os.getenv("W11_DATABASE_URL", "")
        if not (dsn or os.getenv("PGSERVICE") or
                all(os.getenv(key) for key in ("PGHOST", "PGDATABASE", "PGUSER"))):
            raise IntegrationBlocked("Week 11 database configuration is absent. Supply existing W11_DATABASE_URL "
                                     "or PGSERVICE or PGHOST/PGDATABASE/PGUSER; no credential discovery or setup is performed.")
        if os.getenv("W11_PROVIDER", "mock") != "mock":
            raise IntegrationBlocked("Week 12 requires the existing mock Week 11 corpus; real embeddings are disabled.")
        store = None
        try:
            dimension = int(os.getenv("W11_DIMENSION", "128"))
            if not 1 <= dimension <= 16000:
                raise ValueError("Invalid dimension")
            provider = MockEmbeddingProvider(dimension)
            store = PgStore.connect(dsn, dimension=dimension, provider_id=f"mock:{dimension}:week9-v1")
            with store.conn.transaction():
                store.conn.execute("SET TRANSACTION READ ONLY")
                store.conn.execute("SET LOCAL statement_timeout = '10s'")
                return store.search(question, provider, self.top_k, self.source_path, self.tags)
        except Exception:
            raise IntegrationBlocked("Week 11 read-only retrieval failed. Check existing connection, schema, "
                                     "permissions and mock dimension; database setup/writes are not available here.") from None
        finally:
            if store is not None:
                store.close()
