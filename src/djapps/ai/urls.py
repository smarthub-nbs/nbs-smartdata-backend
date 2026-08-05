from django.urls import path

from djapps.ai.views import AiSearchAnswerView


urlpatterns = [
    path("search/ai-answer/", AiSearchAnswerView.as_view(), name="ai-search-answer"),
]

