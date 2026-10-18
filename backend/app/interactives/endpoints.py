"""Endpoint checks that run before any credential is attached to a request."""

from urllib.parse import urlsplit

DAYTONA_HOST_SUFFIX = "daytona.io"


def validate_daytona_api_url(url: str) -> str:
    """Return the host of a Daytona API URL, or raise ``ValueError`` without echoing the URL."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password:
        raise ValueError("the Daytona API URL must be https without embedded credentials")
    if parts.port not in (None, 443):
        raise ValueError("the Daytona API URL must use the standard https port")
    if host != DAYTONA_HOST_SUFFIX and not host.endswith(f".{DAYTONA_HOST_SUFFIX}"):
        raise ValueError("the Daytona API URL host must belong to daytona.io")
    return host
