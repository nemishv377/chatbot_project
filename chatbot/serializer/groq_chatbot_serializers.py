from rest_framework import serializers
from rest_framework import status


class ChatRequestSerializer(serializers.Serializer):
    """
    Serializer for chatbot request payload.

    Fields:
        message (str): The user's input message. Required for every request.

        session_id (str, optional):
            - On the first query, you will receive a new `session_id` in the response.
            - For subsequent queries in the same conversation, you must pass this `session_id` to continue the session.
            - If no `session_id` is provided, a new session will be created and considered as a new chat.
    """

    message = serializers.CharField(required=True, allow_blank=False)
    session_id = serializers.CharField(required=False)
