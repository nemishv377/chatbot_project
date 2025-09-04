import uuid

from django.db import models

from chatbot_project.enums import MessageBy
from chatbot_project.models import ActiveModelMixin
from chatbot_project.models import BaseModel
from chatbot_project.models import DeleteModelMixin


class ChatSession(ActiveModelMixin, BaseModel, DeleteModelMixin):
    """
    Stores a chat session with a label (first user question).
    """

    session_id = models.CharField(
        max_length=36,  # enough to store uuid4 hex with hyphens
        unique=True,
    )
    label = models.TextField(blank=True)  # Will store first user question
    last_interaction = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} - {str(self.session_id)}"


class Chat(BaseModel):
    """
    Stores each message (user or assistant) linked to a session.
    """

    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="messages"
    )
    message_by = models.CharField(
        max_length=50,
        choices=MessageBy.choices,
        verbose_name="Message By",
    )
    message = models.TextField()

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"
