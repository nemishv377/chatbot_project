from django.urls import path

from .views import ChatbotView
from .views import CustomChatbotView
from .views import DocumentUploadView

urlpatterns = [
    path("", ChatbotView.as_view(), name="chatbot"),
    path("custom/", CustomChatbotView.as_view(), name="custom-chatbot"),
    path("rag/upload/", DocumentUploadView.as_view(), name="rag-upload"),
]
