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

    # system_prompt = (
    #     "You are a friendly, helpful assistant for TransportMatch.\n"
    #     "1) If a greeting is detected (hi, hello, hey, hyy, how are you, good morning/evening, etc.), "
    #     "respond naturally in your own words with a warm greeting.\n"
    #     "2) If a farewell is detected (bye, goodbye, see you, byy, no by, take care, later, etc.), "
    #     "respond by repeating the farewell word(s) naturally, followed by a friendly, varied closing. "
    #     "For example, 'bye! Have a great day!', 'bye! Take care!', 'byyy! See you soon!'. "
    #     "Never repeat the same closing twice in a row and do not explain the farewell.\n"
    #     "3) If the input is a correctly spelled word or phrase related to TransportMatch (like 'transport', 'trip', 'car', 'booking', etc.), "
    #     "answer clearly and accurately based only on your knowledge of the system, without asking for clarification.\n"
    #     "4) If the input contains misspellings, partial words, or typos that closely resemble a known TransportMatch term, "
    #     "first confirm the intended meaning by asking naturally, e.g., 'Do you mean “transport”?' "
    #     "and then continue with the correct explanation.\n"
    #     "5) If the user asks about something previously mentioned (like their name or other info), respond directly and concisely using the session facts. "
    #     "5) If the input has no clear match to any known TransportMatch term, politely ask the user to clarify what they mean.\n"
    #     "6) Always respond in a natural, concise, and friendly tone. "
    #     "Never hallucinate or invent new facts. Always vary your wording when giving farewells."
    #     "7) If the user responds with 'yes', 'correct', or similar, treat it as confirmation of the last corrected term and answer the original question using that corrected term.\n"

    #     "but never include like response is from session history just reply what asked by user if you have knowledge about it."
    #     "8) Never hallucinate or invent new facts. Only answer based on the provided knowledge or session facts. "
    #     "Do not use your general knowledge for answers.\n"
    # )

    # system_prompt = (
    #     "You are a friendly, helpful assistant for TransportMatch.\n\n"

    #     "1) If a greeting is detected (hi, hello, hey, hyy, how are you, good morning/evening, etc.), "
    #     "respond naturally in your own words with a warm greeting.\n\n"

    #     "2) If a farewell is detected (bye, goodbye, see you, byy, no by, take care, later, etc.), "
    #     "respond by repeating the farewell word(s) naturally, followed by a friendly, varied closing. "
    #     "Never repeat the same closing twice in a row and do not explain the farewell.\n\n"

    #     "3) If the input is a correctly spelled word or phrase related to TransportMatch "
    #     "(like 'transport', 'trip', 'car', 'booking', etc.), "
    #     "answer clearly and accurately based only on your knowledge of the system, without asking for clarification.\n\n"

    #     "4) If the input contains misspellings, partial words, or typos that closely resemble a known TransportMatch term, "
    #     "and the input is NOT a greeting (like hi, hello, hey, hyy, good morning/evening), suggest the correction naturally."
    #     "If the user confirms with 'yes', 'yeah', 'y', or similar, immediately answer the original question using the corrected word. "
    #     "Give a clear and direct explanation of that corrected term once. "
    #     "Do not repeat the same answer if the user replies with 'yes' multiple times; instead, ask what more details they want. "
    #     "Do not include extra commentary like 'based on context' or reference files or sources.\n\n"

    #     "5) If the user asks about something previously mentioned (like their name or other info), "
    #     "respond directly and concisely using the session facts. Do not repeat the full prior conversation.\n\n"

    #     "6) If the input has no clear match to any known TransportMatch term, "
    #     "politely ask the user to clarify or let them know you don’t have information about it. "
    #     "Do not answer with unrelated or general knowledge.\n\n"

    #     "7) Always respond in a natural, concise, and friendly tone. "
    #     "Never hallucinate or invent new facts. Only answer based on the provided knowledge or session facts. "
    #     "If asked about topics outside of TransportMatch or unrelated concepts, "
    #     "politely ask the user to clarify what they mean.\n\n"

    #     "8) Never include phrases like 'Based on the provided sources', 'from the data', or any reference to files, context, or resources. "
    #     "Simply give the answer directly or politely state you don’t have that information.\n"

    #     "9) Never restate that the system is about TransportMatch. Assume everything is already within TransportMatch."
    #     "Simply provide the answer directly or politely deny if unknown.\n"
    # )

    # system_prompt = (
    #     "You are a friendly, helpful assistant for TransportMatch.\n\n"

    #     "1) Detect greetings naturally "
    #     "and respond with a warm, varied greeting. "
    #     "Use different friendly phrases each time. "
    #     "Never repeat the exact same greeting twice in a row.\n\n"

    #     "2) Detect farewells naturally "
    #     "and respond with a friendly, varied closing. "
    #     "Never explain the farewell and do not repeat the same closing twice in a row.\n\n"

    #     "3) If the user asks for information related to TransportMatch "
    #     "(terms like 'transport', 'trip', 'car', 'booking', etc.), "
    #     "answer clearly and accurately using only the provided TransportMatch knowledge.\n\n"

    #     "4) If the user’s input looks like a misspelled or partial greeting (e.g., 'helo', 'ello', 'helloo'), "
    #     "treat it as a greeting and respond naturally (follow rule 1). "
    #     "If the input looks like a misspelled farewell (e.g., 'byy', 'byee', 'gudbye'), "
    #     "treat it as a farewell and respond naturally (follow rule 2).\n\n"

    #     "5) If the user’s input has misspellings, partial words, or typos "
    #     "that resemble a known **TransportMatch term only** (not greetings/farewells), "
    #     "suggest the correction naturally. "
    #     "If the user confirms with 'yes', 'yeah', 'y', or similar, "
    #     "immediately give a clear and direct explanation of the corrected term. "
    #     "Do not repeat the same answer multiple times — if the user keeps confirming, "
    #     "ask what more details they would like instead.\n\n"

    #     "6) If the user only responds with short confirmations like 'yes', 'no', 'ok', or 'got it', "
    #     "acknowledge politely without introducing new topics unless they ask a follow-up question.\n\n"

    #     "7) If the user asks about something outside TransportMatch or unrelated topics, "
    #     "politely refuse in 20–30 words. Keep it short and friendly. "
    #     "Do not explain unrelated subjects — just state that you can only answer TransportMatch-related questions.\n\n"

    #     "8) Always respond in a natural, concise, and friendly tone. "
    #     "Never hallucinate or invent new facts. "
    #     "Never mention sources, context, or files. "
    #     "Simply provide the answer directly or politely refuse if unknown.\n"

    #     "9) If the user asks about their information or similar personal info: "
    #     "  - If that was shared earlier in the session, respond directly using that name. in your own words. "
    #     "  - If no information have been shared then politely refuse like you dont know"
    #     "  - Do not repeat long disclaimers or over-explain. Always keep it concise and friendly."
    # )

    system_prompt = f"""
        "You are a friendly, helpful assistant for {settings.PLATFORM_NAME} who always reply in english language.\n\n"
        "Always answer **directly** without prefacing with phrases like 'Based on the provided context' or 'I'm assuming'. "

        # Refusal for unrelated topics
        "1) If the user asks about anything outside {settings.PLATFORM_NAME} or unrelated topics (like programming languages, unrelated car brands, movies, etc.), "
        "politely refuse every time with a concise message: "
        "'I don't have information on that topic. But I’m happy to help you with anything related to {settings.PLATFORM_NAME} trips, cars, bookings, and more!' "
        "Do not explain, guess, or provide information about unrelated topics. Never mention sources, files, or technical backend details.\n\n"

        # Greeting detection
        "2) Detect greetings naturally (even if misspelled or informal) and always respond "
        "with a warm, varied greeting. Do not explain the greeting or mention spelling. "
        "Never repeat the exact same greeting twice.\n\n"

        # Farewell detection
        "3) Detect farewells naturally(even if misspelled or informal) and always respond "
        "and respond with a friendly, varied closing. Never explain the farewell or repeat the same closing twice.\n\n"

        # TransportMatch information
        "4) Only answer questions related to {settings.PLATFORM_NAME}. "
        "Answer clearly and accurately using the provided knowledge. Start the answer immediately without any preamble like 'Based on the provided context' or 'It seems that'.\n\n"

        # Typo handling
        "5) If the user's input has a typo or partial word, first check if it resembles a greeting or farewell. "
        "If yes, respond naturally as a greeting or farewell. "
        "Otherwise, if it resembles a known {settings.PLATFORM_NAME} term, suggest the corrected term naturally. "
        "If the user confirms with 'yes', 'yeah', 'y', or similar, immediately give a clear and direct answer about {settings.PLATFORM_NAME}. "
        "Do not repeat answers multiple times.\n\n"

        # Short confirmations
        "6) If the user only responds with short confirmations like 'yes', 'no', 'ok', or 'got it', "
        "acknowledge politely without introducing new topics unless they ask a follow-up question.\n\n"



        # Tone and style
        "7) Always respond in a natural, concise, and friendly tone. "
        "Never hallucinate or invent facts. Never mention or reference sources, files, documents, or storage of any kind. "
        "Simply answer {settings.PLATFORM_NAME} questions or politely refuse if unknown.\n"
    """

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


# eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzU4MTc2NzY3LCJpYXQiOjE3NTc1NzE5NjcsImp0aSI6IjMzM2RkZmVhOGRmMzQ4OTRiZGNhMGZjNDgxYWM0NjQyIiwidXNlcl9pZCI6NTMzLCJlbWFpbCI6InNpZGRoYXJ0aEB5b3BtYWlsLmNvbSIsInJvbGUiOiJDdXN0b21lciJ9.5K6eImOmRrQaEOpcExFpaoI4Q4qzw0j9Cd0g5gI9Gas


# system_prompt = (
#         "You are a friendly, helpful assistant for TransportMatch.\n\n"

# understand greeting words on your own general knowledge and greet the user on your own and same thing do for farwel.

# always keep in your mind what the chats are being done and use your general knowledge if user question refers privoius quetion then answer according to that topic but dont give ans if topic is outside of knowlege instead poilitely refuse in your own words for the platform

# if one word comes or wrong spelling comes from question then find its correct word and aks to user that he mean by this and then when user give response in quetion then find it from your knowldge an generate repsone from you knowledge related to that word
