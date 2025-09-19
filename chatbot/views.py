import json
import os
import uuid

import markdown2
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from groq import Groq

from chatbot.models import Chat
from chatbot.models import ChatSession
from chatbot.models import MessageBy
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


@csrf_exempt
def home_page(request):
    """
    Render the chatbot home page.

    This view displays the entry point for the chatbot feature,
    showing navigation links to both chatbot types (e.g., general
    chatbot and knowledge-based chatbot). It does not handle any
    form submissions or data processing.

    Returns:
        HttpResponse: Rendered HTML page (chatbot/home.html).
    """
    return render(request, "chatbot/home.html")


@csrf_exempt
def general_chat_page(request):
    """
    Render the general chatbot UI.

    This view serves the frontend template for the general chatbot,
    which behaves like ChatGPT. It provides the chat interface where
    users can start new conversations or continue an existing one
    based on their session_id.

    Returns:
        HttpResponse: Rendered HTML page (chatbot/general_chat.html).
    """
    return render(request, "chatbot/chat.html")


@csrf_exempt
def general_chatbot_session_view(request, session_id=None):
    """
    Session-based view for the general chatbot (ChatGPT-like).

    This endpoint supports both retrieving existing chat history
    and sending new user messages within a session.

    **Supported Methods**:
        - GET:
            • If `session_id` is provided → fetch all chat messages for that session.
            • If no `session_id` is provided → create a new session and return an empty history.

        - POST:
            • Accepts a user message and optional `session_id`.
            • If no `session_id` is provided, a new chat session is created.
            • Stores the user message in the database.
            • Prepares a system prompt (from DOMAIN_PROMPTS).
            • Retrieves conversation history for context.
            • Calls the Groq API to generate an AI response.
            • Saves the assistant’s response in the database.
            • Returns the AI response and current session ID.

    **Workflow for POST**:
        1. Validate the incoming request payload.
        2. Create or retrieve the associated ChatSession.
        3. Save the user’s message.
        4. Build full conversation history.
        5. Prepend the system prompt for the LLM.
        6. Query the Groq model for a response.
        7. Convert the response to HTML (markdown → HTML).
        8. Save and return the AI’s reply with the session ID.

    Args:
        request (HttpRequest): Incoming HTTP request (GET or POST).
        session_id (str, optional): Chat session identifier.

    Returns:
        JsonResponse:
            • GET → {"history": [...], "session_id": str}
            • POST → {"answer": str (HTML), "session_id": str}
            • On error → {"error": str}
    """
    # ------------------------------------------------------------------
    # GET → return history
    # ------------------------------------------------------------------
    if request.method == "GET":
        if session_id:
            chat_messages = Chat.objects.filter(
                session__session_id=session_id
            ).order_by("created_at")
            history = [
                {"role": m.message_by.lower(), "message": m.message}
                for m in chat_messages
            ]
            return JsonResponse({"history": history, "session_id": session_id})
        else:
            # create new session
            new_session_id = str(uuid.uuid4())
            ChatSession.objects.create(session_id=new_session_id)
            return JsonResponse({"history": [], "session_id": new_session_id})

    # ------------------------------------------------------------------
    # POST → process message
    # ------------------------------------------------------------------
    elif request.method == "POST":
        """
        Handle incoming chat messages and generate AI responses.

        Workflow:
        1. Parse and validate the request payload.
        2. Create or retrieve a ChatSession:
        - If no `session_id` is provided, start a new session.
        - Otherwise, continue the existing conversation.
        3. Retrieve and persist conversation history.
        4. Build the full message sequence with:
        - A domain-specific system prompt (from DOMAIN_PROMPTS).
        - Previous chat history for context.
        - The current user message.
        5. Send the conversation to the Groq API for an AI-generated response.
        6. Convert the AI response from Markdown to HTML.
        7. Save the assistant response in the database.
        8. Return the AI response and session_id in a JSON response.

        Returns:
            JsonResponse: {
                "answer": <str>  # AI response as HTML,
                "session_id": <str>  # Current or newly created session ID
            }
        """

        # def post(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                # Validate input
                payload = json.loads(request.body)
                user_message = payload.get("question", "").strip()
                session_id = payload.get("session_id")

                # Get or create chat session
                chat_session, created = ChatSession.objects.get_or_create(
                    session_id=session_id or str(uuid.uuid4()),
                    defaults={
                        "label": user_message,
                        "last_interaction": timezone.now(),
                    },
                )

                # Prepare system prompt
                prompt_domain = getattr(settings, "PROMPT_DOMAIN", "general")
                system_prompt = DOMAIN_PROMPTS.get(
                    prompt_domain, DOMAIN_PROMPTS[settings.PROMPT_DOMAIN]
                )

                # Retrieve previous chats
                chats = Chat.objects.filter(session=chat_session)

                # Save current user message
                Chat.objects.create(
                    session=chat_session,
                    message_by=MessageBy.USER,
                    message=user_message,
                )

                # Build conversation history
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

                # Call Groq API for AI response
                client = Groq(api_key=settings.GROQ_API_KEY)
                chat_completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages_for_llm,
                    temperature=0.7,
                    max_tokens=10000,
                )

                ai_reply = chat_completion.choices[0].message.content

                # convert markdown to html
                answer_html = markdown2.markdown(ai_reply)

                # Save assistant response
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

                return JsonResponse(
                    {
                        "answer": answer_html,
                        "session_id": chat_session.session_id,
                    },
                    status=200,
                )

        except Exception as e:
            chatbot_logger.error(f"{e}, {messages.SOMETHING_WENT_WRONG}")
            return JsonResponse(
                {"error": "Something went wrong. Please try again later."},
                status=400,
            )
    else:
        chatbot_logger.error(f"{e}, {messages.SOMETHING_WENT_WRONG}")
        return JsonResponse(
            {"error": "Something went wrong. Please try again later."},
            status=400,
        )
