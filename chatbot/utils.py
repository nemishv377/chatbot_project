# chatbot/utils.py
import hashlib
import os
import re
from typing import Any
from typing import Dict
from typing import List

import chromadb
import pandas as pd
import pytesseract
import requests
from bs4 import BeautifulSoup  # HTML scraping
from django.conf import settings
from docx import Document as DocxDocument
from PIL import Image  # Image OCR (requires tesseract on the OS)
from pptx import Presentation  # File parsers
from PyPDF2 import PdfReader  # PDF / DOCX / TXT

from chatbot.models import Chat
from chatbot_project.enums import MessageBy


# ----------------------------------------------------------------------
# 1️⃣ ChromaDB collection helper
# ----------------------------------------------------------------------
def get_chroma_collection() -> chromadb.Collection:
    """
    Returns a persisted Chroma collection named "knowledge".
    Uses PersistentClient API and ensures path exists.
    """
    persist_dir = getattr(settings, "CHROMA_PERSIST_DIR", None)

    if not persist_dir:
        # fallback to a local "chroma_db" folder inside project root
        persist_dir = os.path.join(settings.BASE_DIR, "chroma_db")

    # Ensure the directory exists
    os.makedirs(persist_dir, exist_ok=True)

    client = chromadb.PersistentClient(path=persist_dir)

    # Create collection if not exists
    try:
        collection = client.get_collection("knowledge")
    except Exception:
        collection = client.create_collection(name="knowledge")

    return collection


# ----------------------------------------------------------------------
# 2️⃣ Text extraction helpers
# ----------------------------------------------------------------------
def _clean_text(text: str) -> str:
    """Collapse whitespace, strip control characters."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_from_pdf(path: str) -> str:
    reader = PdfReader(path)
    txt = ""
    for page in reader.pages:
        txt += page.extract_text() or ""
    return _clean_text(txt)


def _extract_from_docx(path: str) -> str:
    doc = DocxDocument(path)
    txt = "\n".join([p.text for p in doc.paragraphs])
    return _clean_text(txt)


def _extract_from_pptx(path: str) -> str:
    prs = Presentation(path)
    texts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                texts.append(shape.text)
    return _clean_text(" ".join(texts))


def _extract_from_excel(path: str) -> str:
    df = pd.read_excel(path, sheet_name=None)  # load all sheets
    texts = []
    for sheet_name, sheet_df in df.items():
        texts.append(sheet_df.to_string(index=False))
    return _clean_text(" ".join(texts))


def _extract_from_csv(path: str) -> str:
    df = pd.read_csv(path)
    return _clean_text(df.to_string(index=False))


def _extract_from_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return _clean_text(f.read())


def _extract_from_html(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
        texts = soup.stripped_strings
        return _clean_text(" ".join(texts))


def _extract_from_image(path: str) -> str:
    """Run OCR on an image file."""
    img = Image.open(path)
    txt = pytesseract.image_to_string(img)
    return _clean_text(txt)


def _extract_from_url(url: str) -> str:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    texts = soup.stripped_strings
    return _clean_text(" ".join(texts))


def extract_content(file_path: str, source_label: str) -> List[Dict[str, Any]]:
    """
    Detect file type, extract raw text, chunk it and return a list of dicts:
    {
        "id": <unique-id>,
        "text": <chunk>,
        "metadata": {"source": <source_label>}
    }
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        raw = _extract_from_pdf(file_path)
    elif ext in (".docx", ".doc"):
        raw = _extract_from_docx(file_path)
    elif ext in (".pptx",):
        raw = _extract_from_pptx(file_path)
    elif ext in (".xlsx", ".xls"):
        raw = _extract_from_excel(file_path)
    elif ext == ".csv":
        raw = _extract_from_csv(file_path)
    elif ext in (".txt", ".md"):
        raw = _extract_from_txt(file_path)
    elif ext in (".html", ".htm"):
        raw = _extract_from_html(file_path)
    elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif", ".webp"):
        raw = _extract_from_image(file_path)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

    chunks = chunk_text(raw)
    out = []
    for i, chunk in enumerate(chunks):
        uid = hashlib.sha256(f"{source_label}-{i}-{chunk}".encode()).hexdigest()
        out.append(
            {
                "id": uid,
                "text": chunk,
                "metadata": {"source": source_label},
            }
        )
    return out


def extract_from_url(url: str) -> List[Dict[str, Any]]:
    """
    Pull a web page, chunk it and return the same structure as `extract_content`.
    """
    raw = _extract_from_url(url)
    chunks = chunk_text(raw)
    out = []
    for i, chunk in enumerate(chunks):
        uid = hashlib.sha256(f"{url}-{i}-{chunk}".encode()).hexdigest()
        out.append(
            {
                "id": uid,
                "text": chunk,
                "metadata": {"source": url},
            }
        )
    return out


# ----------------------------------------------------------------------
# 3️⃣ Chunking logic
# ----------------------------------------------------------------------
def chunk_text(
    text: str, chunk_size: int = 500, overlap: int = 100, separator: str = " "
) -> List[str]:
    """
    Very simple sliding-window splitter.
    - `chunk_size` = approx. number of characters per chunk.
    - `overlap`   = characters that overlap between consecutive chunks.
    Returns a list of strings.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap  # step back for overlap
    return chunks


# ----------------------------------------------------------------------
# 4️⃣ Retrieval
# ----------------------------------------------------------------------
def retrieve_relevant_chunks(
    collection: chromadb.Collection,
    query: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Embed the query, perform a similarity search, and return the raw
    documents (including metadata) that the LLM will see.
    """
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        # include=["documents", "metadatas", "distances", "ids"]  # ✅ valid fields
        include=["documents", "metadatas", "distances"],  # ✅ valid fields
    )

    docs = []
    # for doc, meta, dist, doc_id in zip(
    #     results["documents"][0],
    #     results["metadatas"][0],
    #     results["distances"][0],
    #     results["ids"][0],
    # ):
    #     docs.append(
    #         {
    #             "id": doc_id,
    #             "text": doc,
    #             "metadata": meta,
    #             "distance": dist,
    #         }
    #     )
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        docs.append(
            {
                "text": doc,
                "metadata": meta,
                "distance": dist,
            }
        )
    return docs


# ----------------------------------------------------------------------
# 5️⃣ Prompt construction
# ----------------------------------------------------------------------
def build_prompt(
    user_message: str, retrieved_chunks: List[Dict[str, Any]], chat_session=None
) -> List[Dict[str, str]]:
    """
    Returns a list of messages in the OpenAI-compatible format that Groq expects:
    [
        {"role": "system", "content": "..."},
        {"role": "user",   "content": "..."},
    ]
    The system prompt tells the model to answer *only* using the supplied context.
    """
    # system_prompt = (
    #     "You are a helpful assistant. "
    #     "Only answer questions using the information provided in the given documents. "
    #     "If the answer is not in the documents, say: "
    #     "'I could not find that information in the provided documents.' "
    #     "Do not use any outside knowledge."
    # )

    # The logged-in user's name for this session is: {request.user.first_name or request.user.username}.
    # Always personalize responses when appropriate by naturally using their name in greetings or confirmations.
    # Never ask the user for their name, since you already know it from the session.
    system_prompt = f"""
        You are a friendly, helpful assistant for {settings.PLATFORM_NAME} who always replies in English.
        Always answer directly without prefacing with phrases like:
        - "Based on the provided context"
        - "According to the documentation"
        - "It seems like"
        - "I'm assuming"
        - "It looks like"

        The logged-in user's name for this session is: kohli sharma.
        Always personalize responses when appropriate by naturally using their name in greetings or confirmations.
        Never ask the user for their name, since you already know it from the session.

        1) Gibberish / unclear input:
        - If the input is completely unreadable (e.g., "?????////\"\"\"\"....\") → respond only with:
        "I didn’t understand what you meant. Could you please rephrase your question?"

        - If the input contains some real words but is still mostly unclear or broken
        (e.g., "????what////what??\'\'\'\", "how///book???///car"),
        respond only with:
        "It seems like your question is unclear. Could you please provide more details or clarify what you need help with regarding {settings.PLATFORM_NAME}? For example, are you asking about a specific feature, a transaction issue, or something else?"

        2) Refusal for unrelated topics:
        If the user asks about anything outside {settings.PLATFORM_NAME} or unrelated topics,
        politely refuse every time with this message:
        "I don't have information on that topic. But I’m happy to help you with anything related to {settings.PLATFORM_NAME}!"

        3) Greeting detection:
        Detect greetings naturally (even if misspelled or informal) and always respond with a warm, varied greeting.
        Do not explain the greeting or mention spelling. Never repeat the exact same greeting twice.

        4) Farewell detection:
        Detect farewells naturally (even if misspelled or informal) and respond with a friendly, varied closing.
        Never explain the farewell or repeat the same closing twice.

        5) TransportMatch information:
        Only answer questions related to {settings.PLATFORM_NAME}.
        Answer clearly and accurately using the provided knowledge.
        Start every answer immediately with the fact itself.
        Do NOT use any of these phrases or similar:
        "It seems like", "Based on", "According to", "It looks like", "I think".
        Never hedge or introduce the answer with filler.

        6) Typo handling:
        If the user's input has a typo or partial word, first check if it resembles a greeting or farewell.
        - If yes → respond naturally as a greeting or farewell.
        - If it resembles a known {settings.PLATFORM_NAME} term → suggest the corrected term naturally.
        - If the user confirms with "yes", "yeah", "y", or similar → immediately give a clear and direct answer.
            → IMMEDIATELY provide the most relevant example, list, or direct information available.
            → DO NOT repeat the earlier refusal or vague answer.
            - If it resembles a known {settings.PLATFORM_NAME} term → suggest the corrected term naturally.
            - If the user confirms ("yes", "yeah", "y") → immediately provide the clear and direct {settings.PLATFORM_NAME} answer.
            - Otherwise → respond only with:
            "I don't have information on that topic. But I’m happy to help you with anything related to {settings.PLATFORM_NAME}!"

        Do not repeat answers multiple times and do not add explanations like
        "It seems you meant..." or "Did you mean...".

        7) Short confirmations:
        If the user only responds with short confirmations like "yes", "no", "ok", or "got it",
        acknowledge politely without introducing new topics unless they ask a follow-up question.

        8) Refusal for unrelated topics (repeated for emphasis):
        If the user asks about anything outside {settings.PLATFORM_NAME} or unrelated topics,
        politely refuse every time with this message:
        "I don't have information on that topic. But I’m happy to help you with anything related to {settings.PLATFORM_NAME}!"

        9) Vague questions:
        If the user's question is vague but matches a known {settings.PLATFORM_NAME} concept,
        answer directly with the available information instead of asking for clarification.

        10) Tone and style:
        Always respond in a natural, concise, and friendly tone.
        Never hallucinate or invent facts.
        Never mention or reference sources, files, documents, or storage.
        Never ask the user to confirm if your answer is correct.
        Never end answers with phrases like:
        "please confirm", "is this correct", "did you mean", or "let me know".


        11) User-facing terminology:
        Never use technical terms like "backend", "frontend", "API", "database", or "server" in your responses.
        Always use user-friendly terms instead, such as:
        - "the platform"
        - "the app"
        - "the system"
        - "on TransportMatch"
        Choose the wording that feels most natural for the user’s perspective.
    """

    # Merge retrieved chunks
    context_parts = []
    for i, chunk in enumerate(retrieved_chunks, start=1):
        src = chunk["metadata"].get("source", "unknown")
        context_parts.append(f"Source {i} ({src}):\n{chunk['text']}\n")
    context_text = (
        "\n".join(context_parts) if context_parts else "No documents provided."
    )

    # Include previous conversation if session is provided
    conversation_history = []
    if chat_session:
        chats = Chat.objects.filter(session=chat_session).order_by("id")
        for chat in chats:
            # role = "user" if chat.message_by == MessageBy.USER else "assistant"
            conversation_history.append(
                {"role": chat.message_by.lower(), "content": chat.message}
            )

    # Append current user message with context
    conversation_history.append(
        {
            "role": "user",
            "content": f"Context:\n{context_text}\n\nUser Message:\n{user_message}",
        }
    )

    # Final messages for LLM
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)  # include old chat history + current message
    return messages
