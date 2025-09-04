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
