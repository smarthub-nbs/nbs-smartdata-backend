from rest_framework import serializers


class AiSearchResultSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=300)
    description = serializers.CharField(max_length=2000, allow_blank=True)
    topic = serializers.CharField(max_length=120, allow_blank=True, required=False)
    region = serializers.CharField(max_length=120, allow_blank=True, required=False)
    source_url = serializers.URLField(allow_blank=True, required=False)
    data_summary = serializers.CharField(
        max_length=2000,
        allow_blank=True,
        required=False,
    )


class AiSearchAnswerRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=500)
    deterministic_answer = serializers.CharField(max_length=4000, allow_blank=True)
    facts = serializers.ListField(
        child=serializers.CharField(max_length=2000),
        allow_empty=True,
        max_length=10,
    )
    results = AiSearchResultSerializer(many=True, required=False)


class AiSearchAnswerResponseSerializer(serializers.Serializer):
    answer = serializers.CharField()
    used_ai = serializers.BooleanField()
    model = serializers.CharField(allow_null=True)
    reason = serializers.CharField(allow_blank=True)

