import uuid

from django.db import models

from chatbot_project.enums import MessageBy
from chatbot_project.enums import SourceType
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


import uuid

from django.db import models


class IngestedDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to="uploads/%Y/%m/%d/")
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    num_chunks = models.IntegerField(default=0)
    status = models.CharField(max_length=30, default="processed")  # processed|error
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name


import uuid

# class IngestedDocument(BaseModel):

#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

#     # Either a file OR a URL will be populated
#     file = models.FileField(
#         upload_to="uploads/%Y/%m/%d/", blank=True, null=True
#     )
#     url = models.URLField(blank=True, null=True)

#     source_type = models.CharField(
#         max_length=20, choices=SourceType.choices, default=SourceType.FILE
#     )

#     original_name = models.CharField(max_length=255, blank=True, default="")
#     mime_type = models.CharField(max_length=100, blank=True, default="")
#     size_bytes = models.BigIntegerField(default=0)

#     num_chunks = models.IntegerField(default=0)
#     status = models.CharField(
#         max_length=30, default="processed"
#     )  # processed | error
#     error_message = models.TextField(blank=True, default="")
#     created_at = models.DateTimeField(auto_now_add=True)

#     def __str__(self):
#         return self.original_name or self.url or str(self.id)
