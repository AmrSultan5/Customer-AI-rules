"""
CLI entry point for RAG ingestion (Phase 8a).

Usage (from backend/):

    python -m ingest --kb customer_sap

Resolves the KB descriptor via the registry and runs ingestion.ingest_kb
against it, printing the resulting document/chunk/skip counts. Also reachable
in-app via `POST /admin/reload?kb=<id>` (providers/rag.py's
RagProvider.reload calls the same ingest_kb).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def main(argv: list[str] | None = None) -> int:
    # Load backend/.env so a standalone CLI run picks up OPENAI_API_KEY (for
    # embeddings) and any DATABASE_URL, same as the app does at startup.
    try:
        from dotenv import load_dotenv

        load_dotenv(_BACKEND_DIR / ".env")
    except ImportError:
        pass

    from ingestion import ingest_kb
    from providers.registry import KnowledgeBaseRegistry

    parser = argparse.ArgumentParser(description="Ingest a KB's RAG source into the vector store.")
    parser.add_argument("--kb", required=True, help="KB descriptor id (backend/kb/<id>.yaml)")
    args = parser.parse_args(argv)

    registry = KnowledgeBaseRegistry()
    descriptor = registry.get_descriptor(args.kb)
    if descriptor is None:
        print(f"Unknown KB: {args.kb!r}", file=sys.stderr)
        return 1

    counts = ingest_kb(descriptor)
    print(
        f"[ingest] kb={descriptor.id} documents={counts['documents']} "
        f"chunks={counts['chunks']} skipped={counts['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
