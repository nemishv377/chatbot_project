from django.urls import path

from chatbot import views
from chatbot.views import assistant_chat_page
from chatbot.views import assistant_chatbot_view
from chatbot.views import general_chat_page
from chatbot.views import general_chatbot_session_view
from chatbot.views import home_page

urlpatterns = [
    path("", home_page, name="home-page"),
    path("general/", general_chat_page, name="general-chat-page"),
    path(
        "general/<str:session_id>/",
        general_chatbot_session_view,
        name="general-chat-history",
    ),  # GET/POST
    path("assistant/", assistant_chat_page, name="assistant-chat-page"),
    path(
        "assistant/<str:session_id>/",
        assistant_chatbot_view,
        name="assistant-chat-history",
    ),  # GET/POST
]
