"""CLI with environment-only connection configuration and redacted errors."""

import argparse
import json
import os
from pathlib import Path
import sys

from .config import provider_from_env
from .ingestion import read_note
from .store import PgStore, SchemaMismatch


def parser():
    root = argparse.ArgumentParser(description="Index one explicit Markdown note; no directory scanning")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the isolated schema or verify an owned schema")
    commands.add_parser("check", help="Verify schema and embedding configuration")
    index = commands.add_parser("index")
    index.add_argument("file", type=Path)
    index.add_argument("--source-path", help="Explicit stable source identity (e.g. integration-test/<uuid>/note.md)")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--source-path")
    search.add_argument("--tag", action="append", default=[], help="Exact case-sensitive tag; repeated tags use ANY")
    delete = commands.add_parser("delete")
    delete.add_argument("source_path", help="Exact indexed source path; cascades only that document's chunks")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    store = None
    try:
        provider, identity = provider_from_env()
        note = read_note(args.file, args.source_path) if args.command == "index" else None
        store = PgStore.connect(os.getenv("W11_DATABASE_URL", ""), dimension=provider.dimension, provider_id=identity)
        if args.command == "init":
            store.initialize()
            result = store.check()
        elif args.command == "check":
            result = store.check()
        elif args.command == "index":
            result = {"status": store.index(note, provider), "source_path": note.document.source_file,
                      "doc_id": note.document.id, "chunks": len(note.chunks)}
        elif args.command == "delete":
            result = {"deleted_documents": store.delete(args.source_path)}
        else:
            result = store.search(args.query, provider, args.top_k, args.source_path, args.tag)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except SchemaMismatch as exc:
        print(f"Schema error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Driver/provider errors can contain DSNs, response bodies or credentials.
        print(f"Operation failed ({type(exc).__name__}); check file, environment, provider and database configuration.", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
