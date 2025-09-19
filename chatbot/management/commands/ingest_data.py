# chatbot/management/commands/ingest_data.py
import json
import os
import pathlib
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from chatbot.utils import extract_content
from chatbot.utils import extract_from_url
from chatbot.utils import get_chroma_collection


class Command(BaseCommand):
    help = (
        "Ingest files or URLs into the Chroma knowledge base.\n"
        "Usage examples:\n"
        "  python manage.py ingest_data --files path/to/file1.pdf path/to/file2.docx\n"
        "  python manage.py ingest_data --urls https://example.com/article.html\n"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--files",
            nargs="+",
            type=str,
            help="Local file paths to ingest (PDF, DOCX, TXT, images).",
        )
        parser.add_argument(
            "--folder",
            type=str,
            help="Folder path containing multiple files to ingest.",
        )
        parser.add_argument(
            "--urls",
            nargs="+",
            type=str,
            help="Web URLs to ingest.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the existing collection before ingesting.",
        )

    def handle(self, *args, **options):
        collection = get_chroma_collection()

        if options["reset"]:
            self.stdout.write(self.style.WARNING("Resetting the collection…"))
            client = get_chroma_collection()._client  # however you get the client
            collection_name = get_chroma_collection().name

            # Delete the whole collection
            client.delete_collection(name=collection_name)

            # Recreate empty collection
            collection = client.create_collection(name=collection_name)
            # collection.delete()
            collection = get_chroma_collection()

        # ------------------------------------------------------------------
        # 1️⃣ Process local files
        # ------------------------------------------------------------------
        files = options.get("files") or []
        for file_path in files:
            abs_path = pathlib.Path(file_path).expanduser().resolve()
            if not abs_path.is_file():
                raise CommandError(f"File not found: {abs_path}")

            source_label = f"file://{abs_path}"
            self.stdout.write(f"Ingesting {abs_path} …")
            try:
                docs = extract_content(str(abs_path), source_label)
                collection.upsert(
                    ids=[d["id"] for d in docs],
                    documents=[d["text"] for d in docs],
                    metadatas=[d["metadata"] for d in docs],
                )
                self.stdout.write(self.style.SUCCESS(f"✓ {abs_path}"))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"✗ {abs_path}: {exc}"))

        # ------------------------------------------------------------------
        # 2️⃣ Process URLs
        # ------------------------------------------------------------------
        urls = options.get("urls") or []
        for url in urls:
            parsed = urlparse(url)
            if not parsed.scheme.startswith("http"):
                raise CommandError(f"Invalid URL: {url}")

            self.stdout.write(f"Ingesting URL {url} …")
            try:
                docs = extract_from_url(url)
                collection.upsert(
                    ids=[d["id"] for d in docs],
                    documents=[d["text"] for d in docs],
                    metadatas=[d["metadata"] for d in docs],
                )
                self.stdout.write(self.style.SUCCESS(f"✓ {url}"))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"✗ {url}: {exc}"))

        # ------------------------------------------------------------------
        # 📂 Process a folder
        # ------------------------------------------------------------------
        folder = options.get("folder")
        if folder:
            folder_path = pathlib.Path(folder).expanduser().resolve()
            if not folder_path.is_dir():
                raise CommandError(f"Folder not found: {folder_path}")

            for abs_path in folder_path.glob("*"):
                if abs_path.is_file():
                    source_label = f"file://{abs_path}"
                    self.stdout.write(f"Ingesting {abs_path} …")
                    try:
                        docs = extract_content(str(abs_path), source_label)
                        collection.upsert(
                            ids=[d["id"] for d in docs],
                            documents=[d["text"] for d in docs],
                            metadatas=[d["metadata"] for d in docs],
                        )
                        self.stdout.write(self.style.SUCCESS(f"✓ {abs_path}"))
                    except Exception as exc:
                        self.stdout.write(self.style.ERROR(f"✗ {abs_path}: {exc}"))

        # ------------------------------------------------------------------
        # 3️⃣ Persist (only needed when a persist directory is set)
        # ------------------------------------------------------------------
        # if getattr(settings, "CHROMA_PERSIST_DIR", ""):
        #     collection.persist()
        #     self.stdout.write(self.style.SUCCESS("✅ Chroma collection persisted."))

        if getattr(settings, "CHROMA_PERSIST_DIR", ""):
            self.stdout.write(
                self.style.SUCCESS("✅ Data ingested (persistence is automatic).")
            )


# python manage.py ingest_data --folder ~/Documents/"transport_match_files"

# python manage.py ingest_data --reset --folder ~/Documents/"transport_match_files"
#
