from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet


SUCCESS_RESPONSE_MARKER = "_smarthub_success_response"


def build_success_payload(data=None, message="Request successful."):
    return {
        "success": True,
        "message": message,
        "data": data,
    }


def success_response(
    data=None,
    message="Request successful.",
    status_code=status.HTTP_200_OK,
):
    response = Response(build_success_payload(data=data, message=message), status=status_code)
    setattr(response, SUCCESS_RESPONSE_MARKER, True)
    return response


class StandardizedResponseMixin:
    action_success_messages = {
        "create": "Resource created successfully.",
        "update": "Resource updated successfully.",
        "partial_update": "Resource updated successfully.",
        "destroy": "Resource deleted successfully.",
    }

    method_success_messages = {
        "DELETE": "Resource deleted successfully.",
        "PATCH": "Resource updated successfully.",
        "PUT": "Resource updated successfully.",
    }

    success_message = None

    def get_success_message(self, response):
        if self.success_message:
            return self.success_message

        action = getattr(self, "action", None)
        if action in self.action_success_messages:
            return self.action_success_messages[action]

        method = getattr(self.request, "method", "")
        if response.status_code == status.HTTP_201_CREATED:
            return "Resource created successfully."

        return self.method_success_messages.get(method, "Request successful.")

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)

        if not isinstance(response, Response):
            return response
        if getattr(response, SUCCESS_RESPONSE_MARKER, False):
            return response
        if getattr(response, "exception", False):
            return response
        if not 200 <= response.status_code < 300:
            return response
        if response.status_code in {204, 205}:
            return response

        response.data = build_success_payload(
            data=response.data,
            message=self.get_success_message(response),
        )
        setattr(response, SUCCESS_RESPONSE_MARKER, True)
        return response


class StandardizedAPIView(StandardizedResponseMixin, APIView):
    pass


class StandardizedModelViewSet(StandardizedResponseMixin, ModelViewSet):
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message="Resource deleted successfully.")


class StandardizedReadOnlyModelViewSet(StandardizedResponseMixin, ReadOnlyModelViewSet):
    pass
