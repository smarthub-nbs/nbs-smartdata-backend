from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from config.api.responses import (
    SUCCESS_RESPONSE_MARKER,
    build_success_payload,
)


class CustomPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100
    page_query_param = "page"

    def get_paginated_data(self, data):
        page_size = self.get_page_size(self.request) or self.page_size
        return {
            "items": data,
            "pagination": {
                "page": self.page.number,
                "page_size": page_size,
                "total_pages": self.page.paginator.num_pages,
                "total_items": self.page.paginator.count,
                "has_next": self.page.has_next(),
                "has_previous": self.page.has_previous(),
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
            },
        }

    def get_paginated_response(self, data):
        response = Response(
            build_success_payload(
                data=self.get_paginated_data(data),
                message="Request successful.",
            )
        )
        setattr(response, SUCCESS_RESPONSE_MARKER, True)
        return response
