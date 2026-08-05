from rest_framework import serializers


class TispCachedSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=500)


class TispCachedDatasetSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    topicSlug = serializers.CharField()
    topicName = serializers.CharField()
    format = serializers.CharField()
    frequency = serializers.CharField()
    region = serializers.CharField()
    keywords = serializers.ListField(child=serializers.CharField())
    publisher = serializers.CharField()
    updatedAt = serializers.CharField()
    recordCount = serializers.IntegerField()
    license = serializers.CharField()
    sourceUrl = serializers.CharField()
    dataSummary = serializers.CharField()
    cached = serializers.BooleanField()


class TispCachedSearchResponseSerializer(serializers.Serializer):
    datasets = TispCachedDatasetSerializer(many=True)

