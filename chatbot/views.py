import os
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from groq import Groq
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from chatbot.models import Chat
from chatbot.models import ChatSession
from chatbot.serializer.groq_chatbot_serializers import ChatRequestSerializer
from chatbot_project import messages
from chatbot_project.enums import MessageBy
from chatbot_project.logging_handler import set_log_file_handler

# -------------------------
# Logger Setup
# -------------------------
filepath = os.path.join(settings.LOG_DIR, "chatbot_log")
chatbot_logger = set_log_file_handler("chatbot_logger", filepath, "chatbot_log.log")

# -------------------------
# Base instruction shared by all domains
# -------------------------
BASE_PROMPT = (
    "Hello! I'm here to help you. "
    "Answer questions strictly within your domain. "
    "If the question is outside your domain, politely refuse. "
    "If the question is about a real-world entity (person, place, organization), "
    "do not mention that you are an AI or language model. "
    "Instead, politely state that you cannot provide that information and optionally offer help with something else. "
    "You may use information that the user has previously shared about themselves in your responses if relevant, "
    "but do not add any extra commentary or answer beyond what is asked."
)

# -------------------------
# Domain-specific prompts
# -------------------------
DOMAIN_PROMPTS = {
    "general": f"You may answer general questions not tied to a specific domain. "
    "Do not reveal anything about your creation, design, or underlying system. "
    "Focus only on providing helpful and relevant information to the user's query.",
    "cricket": f"{BASE_PROMPT} You are an expert in cricket rules, players, matches, records, and strategies. "
    "After answering, ask if the user wants more cricket insights or stats.",
    "travel": f"{BASE_PROMPT} You are a travel planner. Answer questions about destinations, itineraries, flights, hotels, and cultural tips.",
    "finance": f"{BASE_PROMPT} You are a financial advisor. Respond about budgeting, investing, banking, and money management.",
    "education": f"{BASE_PROMPT} You are an academic tutor. Answer questions about school subjects, college topics, study tips, or explanations of concepts.",
    "fitness": f"{BASE_PROMPT} You are a fitness trainer. Provide guidance on exercise routines, diet plans, and healthy lifestyle choices.",
    "technology": f"{BASE_PROMPT} You are a technology support assistant. Help with troubleshooting, software, hardware, and IT best practices.",
    "restaurant": f"{BASE_PROMPT} You are a restaurant management assistant. Answer questions about reservations, menus, staff, and customer service.",
    "legal": f"{BASE_PROMPT} You are a legal information assistant. Provide insights about laws, contracts, compliance, and general legal processes.",
    "hospital": f"{BASE_PROMPT} You are a hospital management assistant. Answer about patients, staff, appointments, and hospital operations.",
}


class ChatbotView(APIView):
    """
    API view for a ChatGPT-like chatbot using Groq.

    This view handles:
    - User messages
    - Session-based conversation history
    - Domain-specific prompts
    - AI responses via Groq API

    Workflow:
    1. Validate request payload with ChatRequestSerializer
    2. Create a new ChatSession if `session_id` is not provided
       - On the first query, a new `session_id` is generated and returned in the response
       - For subsequent queries in the same conversation, the client should provide this `session_id`
       - If no `session_id` is provided, a new session is created and considered a new chat
    3. Retrieve previous chats for the session
    4. Append the current user message
    5. Prepare system prompt using DOMAIN_PROMPTS for the selected domain
    6. Call Groq API to generate AI response
    7. Store the assistant's response in the database
    8. Return the AI response along with session information
    """

    def post(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                # -------------------------
                # Validate input
                # -------------------------
                serializer = ChatRequestSerializer(data=request.data)
                if not serializer.is_valid():
                    return Response(
                        serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

                user_message = serializer.validated_data["message"]
                session_id = serializer.validated_data.get("session_id")
                response = {}

                # -------------------------
                # Get or create chat session
                # -------------------------
                chat_session, created = ChatSession.objects.get_or_create(
                    session_id=session_id or str(uuid.uuid4()),
                    defaults={
                        "label": user_message,
                        "last_interaction": timezone.now(),
                    },
                )

                # Include session_id in response only if newly created
                if created:
                    response = {"session_id": chat_session.session_id}

                # -------------------------
                # Prepare system prompt
                # -------------------------
                prompt_domain = getattr(settings, "PROMPT_DOMAIN", "general")
                system_prompt = DOMAIN_PROMPTS.get(
                    prompt_domain, DOMAIN_PROMPTS[settings.PROMPT_DOMAIN]
                )

                # -------------------------
                # Retrieve previous chats
                # -------------------------
                chats = Chat.objects.filter(session=chat_session)

                # -------------------------
                # Save current user message
                # -------------------------
                Chat.objects.create(
                    session=chat_session,
                    message_by=MessageBy.USER,
                    message=user_message,
                )

                # -------------------------
                # Build conversation history
                # -------------------------
                conversation_history = [
                    {"role": chat.message_by.lower(), "content": chat.message}
                    for chat in chats
                ]
                conversation_history.append(
                    {"role": MessageBy.USER.value.lower(), "content": user_message}
                )

                messages_for_llm = [
                    {"role": "system", "content": system_prompt}
                ] + conversation_history

                # -------------------------
                # Call Groq API for AI response
                # -------------------------
                client = Groq(api_key=settings.GROQ_API_KEY)
                chat_completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages_for_llm,
                    temperature=0.7,
                    max_tokens=10000,
                )

                ai_reply = chat_completion.choices[0].message.content
                response["answer"] = ai_reply

                # -------------------------
                # Save assistant response
                # -------------------------
                Chat.objects.create(
                    session=chat_session,
                    message_by=MessageBy.ASSISTANT,
                    message=ai_reply,
                )
                conversation_history.append(
                    {"role": MessageBy.ASSISTANT.value.lower(), "content": ai_reply}
                )
                chat_session.last_interaction = timezone.now()
                chat_session.save()

                # -------------------------
                # Return response
                # -------------------------
                return Response(
                    data={"data": response},
                    status=status.HTTP_200_OK,
                )

        except Exception as e:
            chatbot_logger.error(f"{e}, {messages.SOMETHING_WENT_WRONG}")
            return Response(
                data={"message": messages.SOMETHING_WENT_WRONG},
                status=status.HTTP_400_BAD_REQUEST,
            )


import os
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from groq import Groq
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from chatbot.serializer.custom_chatbot_serializers import ChatRequestSerializer
from chatbot.serializer.custom_chatbot_serializers import FileUploadSerializer

from .models import Chat
from .models import ChatSession
from .models import IngestedDocument
from .models import MessageBy
from .rag_utils import get_relevant_chunks
from .rag_utils import ingest_file_to_chroma


# -------------------------
# File Upload & Ingest
# -------------------------
class DocumentUploadView(APIView):
    """
    POST /api/rag/upload/
    Form-Data: file=<binary>, source=<optional tag>
    Saves to MEDIA_ROOT, extracts text (OCR for images), chunks, embeds to ChromaDB.
    """

    def post(self, request, *args, **kwargs):
        serializer = FileUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        up_file = serializer.validated_data["file"]
        source = serializer.validated_data.get("source") or up_file.name

        # Save file to MEDIA
        subdir = "uploads"
        save_path = os.path.join(subdir, up_file.name)
        full_path = default_storage.save(save_path, ContentFile(up_file.read()))
        abs_path = os.path.join(settings.MEDIA_ROOT, full_path)

        # Ingest → Chroma
        try:
            num_chunks, extractor = ingest_file_to_chroma(
                abs_path, source_name=up_file.name
            )
            doc = IngestedDocument.objects.create(
                file=full_path,
                original_name=up_file.name,
                mime_type=up_file.content_type or "",
                size_bytes=up_file.size or 0,
                num_chunks=num_chunks,
                status="processed" if num_chunks > 0 else "error",
                error_message=""
                if num_chunks > 0
                else "No text found or OCR unavailable",
            )
            return Response(
                {
                    "id": str(doc.id),
                    "file": doc.original_name,
                    "stored_at": doc.file.url
                    if hasattr(doc.file, "url")
                    else doc.file.name,
                    "mime": doc.mime_type,
                    "size": doc.size_bytes,
                    "num_chunks": doc.num_chunks,
                    "extractor": extractor,
                    "status": doc.status,
                },
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            doc = IngestedDocument.objects.create(
                file=full_path,
                original_name=up_file.name,
                mime_type=up_file.content_type or "",
                size_bytes=up_file.size or 0,
                num_chunks=0,
                status="error",
                error_message=str(e),
            )
            return Response(
                {
                    "id": str(doc.id),
                    "file": doc.original_name,
                    "status": "error",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# -------------------------
# Chat (RAG)
# -------------------------
class CustomChatbotView(APIView):
    """
    POST /api/rag/chat/
    Body: { "message": "...", "session_id": "..."? }
    Retrieval-augmented answer based only on uploaded documents.
    """

    def post(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                serializer = ChatRequestSerializer(data=request.data)
                if not serializer.is_valid():
                    return Response(
                        serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

                user_message = serializer.validated_data["message"]
                session_id = serializer.validated_data.get("session_id")
                response = {}

                chat_session, created = ChatSession.objects.get_or_create(
                    session_id=session_id or str(uuid.uuid4()),
                    defaults={
                        "label": user_message,
                        "last_interaction": timezone.now(),
                    },
                )
                if created:
                    response["session_id"] = chat_session.session_id

                # Retrieve context from docs
                retrieved_chunks = get_relevant_chunks(user_message, top_k=20)
                messages_for_llm = [
                    {
                        "role": "system",
                        "content": f"You are a helpful assistant for {settings.PLATFORM_NAME}.",
                    },
                    {
                        "role": "user",
                        "content": f"Here is the relevant documentation:\n{retrieved_chunks}\n\nQuestion: {user_message}",
                    },
                ]

                # Save user message
                Chat.objects.create(
                    session=chat_session,
                    message_by=MessageBy.USER,
                    message=user_message,
                )

                # Build conversation history
                chats = Chat.objects.filter(session=chat_session).order_by("id")
                conversation_history = [
                    {"role": chat.message_by.lower(), "content": chat.message}
                    for chat in chats
                ]
                conversation_history.append(
                    {"role": MessageBy.USER.value.lower(), "content": user_message}
                )
                system_prompt = f"""
                    You are QuickAssist, a helpful assistant for {settings.PLATFORM_NAME}.

                    Rules:
                    - Only use the provided knowledge from the retrieved documents: {retrieved_chunks}.
                    - If the retrieved knowledge is empty OR the user question is not related to {settings.PLATFORM_NAME},
                    do NOT answer using general knowledge.
                    - Instead, politely redirect the user while echoing their input.
                    Example format: "It seems like you might be asking about something unrelated to {settings.PLATFORM_NAME}.
                    If you're referring to a {settings.PLATFORM_NAME}-specific issue or topic, could you please provide more details?"
                    - Never provide unrelated technical explanations (like Python, general programming, etc.).
                    - Keep responses simple, professional, and conversational.
                    """

                messages_for_llm = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Here is the relevant documentation:\n{retrieved_chunks}\n\nQuestion: {user_message}",
                    },
                ]

                # messages_for_llm.append(
                #     {"role": "system", "content": system_prompt},
                #     *conversation_history,
                # )

                client = Groq(api_key=settings.GROQ_API_KEY)
                chat_completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages_for_llm,
                    temperature=0.7,
                    max_tokens=10000,
                )
                ai_reply = chat_completion.choices[0].message.content

                # Optional: sanitize if model slips (hard-guard)
                # DISALLOWED_HINTS = ["i am not allowed", "as an ai", "as a language model",
                #                     "my responses come from", "the system", "who built me", "openai", "meta"]
                # if any(h in ai_reply.lower() for h in DISALLOWED_HINTS):
                #     ai_reply = "I don’t have information on that."

                response["answer"] = ai_reply

                # Save assistant response
                Chat.objects.create(
                    session=chat_session,
                    message_by=MessageBy.ASSISTANT,
                    message=ai_reply,
                )
                chat_session.last_interaction = timezone.now()
                chat_session.save()
                print(conversation_history)

                return Response({"data": response}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
