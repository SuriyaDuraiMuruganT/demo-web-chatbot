#!/usr/bin/env python3
"""
scripts/ingest_documents.py — Command-line Document Ingestion Tool

Usage:
    python scripts/ingest_documents.py --tenant demo-company --file knowledge/demo_faq.md --title "Demo FAQ"
    python scripts/ingest_documents.py --tenant demo-company --dir knowledge/ --approve

This script runs the same ingestion pipeline as the API but from the command line,
making it easy to load sample data and automate document management.

Requirements:
- Database must be running and migrations applied
- OPENAI_API_KEY must be set (for embeddings)
- DATABASE_URL must be set

Security note: Only run this script in a trusted environment with appropriate credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env
from dotenv import load_dotenv
load_dotenv()


async def ingest_file(
    file_path: Path,
    tenant_slug: str,
    title: str | None,
    source_url: str | None,
    auto_approve: bool,
) -> None:
    """Ingest a single file into the knowledge base."""
    from sqlalchemy import select
    from app.database import get_session_factory
    from app.models.tenant import Tenant
    from app.services.ingestion_service import IngestionService

    session_factory = get_session_factory()
    service = IngestionService()

    # Read file
    file_content = file_path.read_bytes()
    doc_title = title or file_path.stem.replace("_", " ").replace("-", " ").title()

    print(f"\n{'='*60}")
    print(f"File:   {file_path.name}")
    print(f"Title:  {doc_title}")
    print(f"Size:   {len(file_content):,} bytes")
    print(f"Tenant: {tenant_slug}")
    print(f"Status: {'auto-approved' if auto_approve else 'pending (needs approval)'}")
    print(f"{'='*60}")

    async with session_factory() as db:
        try:
            # Resolve tenant
            result = await db.execute(
                select(Tenant).where(Tenant.slug == tenant_slug)
            )
            tenant = result.scalar_one_or_none()
            if not tenant:
                print(f"ERROR: Tenant '{tenant_slug}' not found.")
                print("Create the tenant first with:")
                print(f"  curl -u admin:password -X POST http://localhost:8000/admin/tenants \\")
                print(f"       -F 'name=Demo Company' -F 'slug={tenant_slug}'")
                sys.exit(1)

            # Ingest
            result = await service.ingest_document(
                file_content=file_content,
                file_name=file_path.name,
                title=doc_title,
                tenant_id=tenant.id,
                db=db,
                source_url=source_url,
                auto_approve=auto_approve,
            )
            await db.commit()

            if result.is_duplicate:
                print(f"[DUPLICATE] {result.message}")
            else:
                print(f"[SUCCESS]")
                print(f"   Document ID:  {result.document_id}")
                print(f"   Chunks:       {result.chunk_count}")
                print(f"   {result.message}")

        except ValueError as e:
            print(f"[VALIDATION ERROR] {e}")
            await db.rollback()
            sys.exit(1)
        except RuntimeError as e:
            print(f"[PROCESSING ERROR] {e}")
            await db.rollback()
            sys.exit(1)
        except Exception as e:
            print(f"[UNEXPECTED ERROR] {type(e).__name__}: {e}")
            await db.rollback()
            sys.exit(1)


async def main(args: argparse.Namespace) -> None:
    """Main ingestion routine."""
    # Check required environment variables
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.")
        print("Set it in your .env file or as an environment variable.")
        sys.exit(1)

    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL is not set.")
        sys.exit(1)

    files_to_process: list[Path] = []

    if args.file:
        p = Path(args.file)
        if not p.exists():
            print(f"ERROR: File not found: {p}")
            sys.exit(1)
        files_to_process.append(p)

    elif args.dir:
        d = Path(args.dir)
        if not d.is_dir():
            print(f"ERROR: Directory not found: {d}")
            sys.exit(1)
        for ext in ("*.txt", "*.md", "*.pdf"):
            files_to_process.extend(sorted(d.glob(ext)))

        if not files_to_process:
            print(f"No .txt, .md, or .pdf files found in: {d}")
            sys.exit(0)

    print(f"\nIngesting {len(files_to_process)} file(s) into tenant '{args.tenant}'")

    for file_path in files_to_process:
        await ingest_file(
            file_path=file_path,
            tenant_slug=args.tenant,
            title=args.title if len(files_to_process) == 1 else None,
            source_url=args.source_url,
            auto_approve=args.approve,
        )

    print(f"\n{'='*60}")
    print(f"Ingestion complete. {len(files_to_process)} file(s) processed.")
    if not args.approve:
        print("\nDocuments are pending approval.")
        print("Approve them via the admin API:")
        print(f"  GET  http://localhost:8000/admin/{args.tenant}/documents")
        print(f"  POST http://localhost:8000/admin/{args.tenant}/documents/{{id}}/approve")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest knowledge documents into the AI Support Chatbot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Ingest a single file (pending approval)
  python scripts/ingest_documents.py --tenant demo-company --file knowledge/demo_faq.md

  # Ingest a single file and auto-approve (trusted admin use only)
  python scripts/ingest_documents.py --tenant demo-company --file knowledge/demo_faq.md --approve

  # Ingest all files in a directory
  python scripts/ingest_documents.py --tenant demo-company --dir knowledge/ --approve

  # With a custom title and source URL
  python scripts/ingest_documents.py --tenant demo-company \\
      --file knowledge/demo_faq.md \\
      --title "Customer FAQ" \\
      --source-url "https://democompany.example.com/faq" \\
      --approve
        """,
    )
    parser.add_argument("--tenant", required=True, help="Tenant slug (e.g., demo-company)")
    parser.add_argument("--file", help="Path to a single file to ingest")
    parser.add_argument("--dir", help="Path to a directory — ingests all .txt/.md/.pdf files")
    parser.add_argument("--title", help="Document title (defaults to file name)")
    parser.add_argument("--source-url", dest="source_url", help="Source URL for the document")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Auto-approve documents immediately (use only for trusted content)",
    )

    args = parser.parse_args()

    if not args.file and not args.dir:
        parser.error("Either --file or --dir must be specified")

    asyncio.run(main(args))
