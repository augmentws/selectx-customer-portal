"""GoCanvas API v3 client: OAuth client credentials, then bearer-token requests.

    POST {token_url}  multipart form: grant_type=client_credentials, client_id, client_secret,
                      scope=api  ->  {"access_token": ..., "expires_in": ...}

The token is cached until shortly before it expires; a 401 refetches it once and retries.
Response bodies hold customer data and are never logged; error messages never include them.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

DEFAULT_TIMEOUT = (10.0, 60.0)  # connect, read
# Refetch the token this long before GoCanvas says it expires.
TOKEN_EXPIRY_MARGIN_SECONDS = 60

log = logging.getLogger(__name__)


class GoCanvasAuthError(Exception):
    """The token endpoint refused the credentials, or couldn't be reached."""


class GoCanvasClient:
    """One operator's GoCanvas access. Thread-safe."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        token_url: str,
        base_url: str,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float | None = None
        self._lock = threading.Lock()

    def _fetch_token(self) -> tuple[str, float | None]:
        form = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": "api",
        }
        try:
            # Multipart, as GoCanvas documents it (`files` with no filename sends plain fields).
            response = requests.post(
                self._token_url,
                files={key: (None, value) for key, value in form.items()},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise GoCanvasAuthError(
                f"Could not reach the GoCanvas token endpoint: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            # The body can echo request details; keep it out of logs and error messages.
            log.error("GoCanvas token fetch failed with status %s", response.status_code)
            raise GoCanvasAuthError(
                f"GoCanvas rejected the credentials (token endpoint returned "
                f"{response.status_code})"
            )
        try:
            body = response.json()
        except ValueError:
            body = None
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            raise GoCanvasAuthError("GoCanvas token response had no access_token")
        expires_in = body.get("expires_in")
        expires_at = (
            time.monotonic() + float(expires_in) - TOKEN_EXPIRY_MARGIN_SECONDS
            if isinstance(expires_in, int | float)
            else None
        )
        log.info("GoCanvas token fetched")
        return token, expires_at

    def get_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            expired = self._token_expires_at is not None and time.monotonic() >= (
                self._token_expires_at
            )
            if self._token is None or expired or force_refresh:
                self._token, self._token_expires_at = self._fetch_token()
            return self._token

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        """GET {base_url}{path} with the bearer token; on 401, refetch the token once."""
        url = f"{self._base_url}/{path.lstrip('/')}"
        response = self._send(url, self.get_token(), **kwargs)
        if response.status_code == 401:
            log.info("GoCanvas returned 401; refetching the token")
            response = self._send(url, self.get_token(force_refresh=True), **kwargs)
        log.info("GoCanvas GET %s -> %s", path, response.status_code)
        return response

    def _send(self, url: str, token: str, **kwargs: Any) -> requests.Response:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        return requests.get(url, headers=headers, timeout=self._timeout, **kwargs)

    def get_submission(self, submission_id: int) -> requests.Response:
        """GET /submissions/{id}: one submission with all its responses."""
        return self.get(f"/submissions/{submission_id}")
