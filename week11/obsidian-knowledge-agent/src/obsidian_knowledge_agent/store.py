"""Live psycopg adapter. All application writes stay in the Week 11 schema."""

from importlib.resources import files
import math

import psycopg
from psycopg.rows import dict_row

from .ingestion import Note, document_id

SCHEMA = "week11_obsidian_agent"
OWNER = "week11-obsidian-knowledge-agent:001"


class SchemaMismatch(ValueError):
    pass


def vector_literal(values, dimension: int) -> str:
    if len(values) != dimension or not all(math.isfinite(x) for x in values):
        raise ValueError("Embedding must have configured dimension and finite values")
    if not any(values):
        raise ValueError("Zero vectors cannot support cosine retrieval; provide nonempty text")
    return "[" + ",".join(str(float(x)) for x in values) + "]"


def search_filters(source_path=None, tags=None):
    clauses, params = [], []
    if source_path is not None:
        clauses.append("d.source_path = %s")
        params.append(source_path)
    if tags:
        clauses.append("d.tags && %s::text[]")
        params.append(tags)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


class PgStore:
    def __init__(self, conn, dimension=128, provider_id="mock:128:week9-v1"):
        if not 1 <= dimension <= 16000:
            raise ValueError("Dimension must be between 1 and 16000")
        self.conn = conn
        self.dimension = dimension
        self.provider_id = provider_id

    @classmethod
    def connect(cls, dsn="", **kwargs):
        return cls(psycopg.connect(dsn, autocommit=True, row_factory=dict_row, connect_timeout=10), **kwargs)

    def close(self):
        self.conn.close()

    def initialize(self):
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(110011)")
            existing = self.conn.execute(
                "SELECT obj_description(oid, 'pg_namespace') AS owner FROM pg_namespace WHERE nspname=%s",
                (SCHEMA,)).fetchone()
            if existing:
                if existing["owner"] != OWNER:
                    raise SchemaMismatch("Schema already exists without task ownership; stop and inspect")
                self.check()
                return
            sql = files("obsidian_knowledge_agent").joinpath("migrations/001_initial.sql").read_text()
            self.conn.execute(sql.replace("__DIMENSION__", str(self.dimension)))
            self.conn.execute(f"INSERT INTO {SCHEMA}.settings VALUES (true, 1, %s, %s)",
                              (self.dimension, self.provider_id))
            self.check()

    def check(self):
        def require(ok, message):
            if not ok:
                raise SchemaMismatch(message + "; inspect schema/configuration, do not drop existing data")

        owner = self.conn.execute(
            "SELECT obj_description(oid, 'pg_namespace') AS owner FROM pg_namespace WHERE nspname=%s",
            (SCHEMA,)).fetchone()
        require(owner and owner["owner"] == OWNER, "Missing or unowned Week 11 schema; run init on an absent schema")
        require(self.conn.execute("SELECT 1 FROM pg_extension WHERE extname='vector'").fetchone(),
                "Missing vector extension")
        columns = self.conn.execute("""
            SELECT c.relname AS tab, a.attname AS col, format_type(a.atttypid,a.atttypmod) AS typ,
                   a.attnotnull AS required
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND a.attnum>0 AND NOT a.attisdropped
        """, (SCHEMA,)).fetchall()
        actual = {(r["tab"], r["col"]): (r["typ"], r["required"]) for r in columns}
        expected = {
            "documents": {"doc_id": "text", "source_path": "text", "title": "text", "tags": "text[]",
                          "modified_at": "timestamp with time zone", "content_hash": "text",
                          "indexed_at": "timestamp with time zone"},
            "chunks": {"chunk_id": "text", "doc_id": "text", "chunk_index": "integer",
                       "heading_path": "text", "content": "text", "embedding": f"vector({self.dimension})"},
            "settings": {"singleton": "boolean", "version": "integer", "dimension": "integer", "provider_id": "text"},
        }
        for table, cols in expected.items():
            for col, typ in cols.items():
                require(actual.get((table, col)) == (typ, True), f"Column mismatch: {table}.{col}, expected {typ} NOT NULL")
        constraints = self.conn.execute("""
            SELECT c.relname AS tab, pg_get_constraintdef(k.oid) AS definition
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s
        """, (SCHEMA,)).fetchall()
        definitions = {(r["tab"], r["definition"]) for r in constraints}
        for item in [("documents", "PRIMARY KEY (doc_id)"), ("documents", "UNIQUE (source_path)"),
                     ("chunks", "PRIMARY KEY (chunk_id)"), ("chunks", "UNIQUE (doc_id, chunk_index)"),
                     ("chunks", f"FOREIGN KEY (doc_id) REFERENCES {SCHEMA}.documents(doc_id) ON DELETE CASCADE"),
                     ("settings", "PRIMARY KEY (singleton)")]:
            require(item in definitions, f"Missing constraint: {item}")
        require(any(tab == "documents" and "btrim(source_path)" in definition and "<> ''::text" in definition
                    for tab, definition in definitions), "Missing nonempty source_path check")
        settings = self.conn.execute(f"SELECT * FROM {SCHEMA}.settings").fetchall()
        require(len(settings) == 1 and settings[0] == dict(singleton=True, version=1,
                    dimension=self.dimension, provider_id=self.provider_id), "Provider/dimension/migration settings mismatch")
        return {"schema": SCHEMA, "version": 1, "dimension": self.dimension, "provider_id": self.provider_id}

    def index(self, note: Note, provider):
        if provider.dimension != self.dimension:
            raise ValueError("Provider dimension differs from store configuration")
        self.check()
        doc = note.document
        with self.conn.transaction():
            # Serialize updates for the same stable document, including its first insert.
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 11))", (doc.id,))
            old = self.conn.execute(f"SELECT content_hash FROM {SCHEMA}.documents WHERE doc_id=%s", (doc.id,)).fetchone()
            if old and old["content_hash"] == note.content_hash:
                return "unchanged"
            vectors = provider.embed_batch([chunk.content for chunk in note.chunks]) if note.chunks else []
            if len(vectors) != len(note.chunks):
                raise ValueError("Provider returned wrong number of vectors")
            literals = [vector_literal(v, self.dimension) for v in vectors]
            self.conn.execute(f"""
                INSERT INTO {SCHEMA}.documents(doc_id,source_path,title,tags,modified_at,content_hash)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (doc_id) DO UPDATE SET source_path=EXCLUDED.source_path,title=EXCLUDED.title,
                    tags=EXCLUDED.tags,modified_at=EXCLUDED.modified_at,content_hash=EXCLUDED.content_hash,indexed_at=now()
            """, (doc.id, doc.source_file, doc.title, note.tags, note.modified_at, note.content_hash))
            self.conn.execute(f"DELETE FROM {SCHEMA}.chunks WHERE doc_id=%s", (doc.id,))
            for chunk, vector in zip(note.chunks, literals, strict=True):
                self.conn.execute(f"""INSERT INTO {SCHEMA}.chunks
                    (chunk_id,doc_id,chunk_index,heading_path,content,embedding) VALUES (%s,%s,%s,%s,%s,%s::vector)""",
                    (chunk.chunk_id, doc.id, chunk.chunk_index, chunk.heading, chunk.content, vector))
        return "updated" if old else "indexed"

    def delete(self, source_path):
        if not source_path.strip():
            raise ValueError("source_path must not be empty")
        self.check()
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 11))", (document_id(source_path),))
            return self.conn.execute(f"DELETE FROM {SCHEMA}.documents WHERE source_path=%s", (source_path,)).rowcount

    def search(self, query, provider, top_k=5, source_path=None, tags=None):
        if not 1 <= top_k <= 1000:
            raise ValueError("top_k must be between 1 and 1000")
        if provider.dimension != self.dimension:
            raise ValueError("Provider dimension differs from store configuration")
        self.check()
        vector = vector_literal(provider.embed_text(query), self.dimension)
        where, params = search_filters(source_path, tags)
        return self.conn.execute(f"""
            SELECT c.chunk_id,c.content,c.heading_path,d.source_path,d.tags,
                   1 - (c.embedding <=> %s::vector) AS similarity
            FROM {SCHEMA}.chunks c JOIN {SCHEMA}.documents d USING(doc_id)
            {where} ORDER BY c.embedding <=> %s::vector, c.chunk_id LIMIT %s
        """, [vector, *params, vector, top_k]).fetchall()
