from rest_framework.throttling import AnonRateThrottle


class AuthCSRFCookieRateThrottle(AnonRateThrottle):
    scope = "auth_csrf"


class AuthSensitiveRateThrottle(AnonRateThrottle):
    scope = "auth_sensitive"


class AuthRefreshRateThrottle(AnonRateThrottle):
    scope = "auth_refresh"
