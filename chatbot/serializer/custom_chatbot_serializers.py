from rest_framework import serializers


class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)
    source = serializers.CharField(required=False, allow_blank=True)


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField()
    session_id = serializers.CharField(required=False, allow_blank=True)
