CANONICAL_SCHEMA_PREFIX = "/api/v1/"
EXCLUDED_CANONICAL_PATHS = {
    "/api/v1/me/",
    "/api/v1/schema/",
}


def keep_canonical_api_endpoints(endpoints, **kwargs):
    filtered = []

    for path, path_regex, method, callback in endpoints:
        normalized_path = path if path.endswith("/") else f"{path}/"
        if not normalized_path.startswith(CANONICAL_SCHEMA_PREFIX):
            continue
        if normalized_path in EXCLUDED_CANONICAL_PATHS:
            continue
        filtered.append((path, path_regex, method, callback))

    return filtered
