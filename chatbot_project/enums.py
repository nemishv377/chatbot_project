from django.db import models


class MessageBy(models.TextChoices):
    """
    Enumeration representing who sent a chat message.

    This class defines the possible message senders in the chat system.
    It can be used to distinguish between messages sent by the user
    and messages sent by the assistant.

    Attributes:
        USER (str): Represents a message sent by the user ("USER").
        ASSISTANT (str): Represents a message sent by the assistant ("ASSISTANT").
    """

    USER = "USER", "User"
    ASSISTANT = "ASSISTANT", "Assistant"
