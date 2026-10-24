"""HTTP client for the ingest API (docs/CONTRACTS.md §2) with dev and Cognito auth."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Protocol

import httpx

KEYRING_SERVICE = "inventory-capture"


class ApiError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.retryable = status in (408, 425, 429) or status >= 500


class Auth(Protocol):
    def headers(self) -> dict[str, str]: ...


class DevAuth:
    def __init__(self, user: str = "dev-operator", groups: str = "operator"):
        self.user, self.groups = user, groups

    def headers(self) -> dict[str, str]:
        return {"x-dev-user": self.user, "x-dev-groups": self.groups}


class CognitoAuth:
    """USER_PASSWORD_AUTH once, then REFRESH_TOKEN_AUTH; the refresh token lives in the OS keyring."""

    def __init__(self, region: str, client_id: str, username: str):
        import boto3

        self.client = boto3.client("cognito-idp", region_name=region)
        self.client_id, self.username = client_id, username
        self._id_token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def login(self, password: str) -> None:
        resp = self.client.initiate_auth(
            ClientId=self.client_id, AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": self.username, "PASSWORD": password},
        )
        self._store(resp["AuthenticationResult"])

    def _store(self, result: dict[str, Any]) -> None:
        import keyring

        self._id_token = result["IdToken"]
        self._expires_at = time.time() + int(result.get("ExpiresIn", 3600)) - 60
        if result.get("RefreshToken"):
            keyring.set_password(KEYRING_SERVICE, self.username, result["RefreshToken"])

    def has_refresh_token(self) -> bool:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, self.username) is not None

    def logout(self) -> None:
        import keyring

        self._id_token = None
        try:
            keyring.delete_password(KEYRING_SERVICE, self.username)
        except keyring.errors.PasswordDeleteError:
            pass

    def headers(self) -> dict[str, str]:
        import keyring

        with self._lock:
            if self._id_token is None or time.time() >= self._expires_at:
                refresh = keyring.get_password(KEYRING_SERVICE, self.username)
                if not refresh:
                    raise PermissionError("not logged in")
                resp = self.client.initiate_auth(
                    ClientId=self.client_id, AuthFlow="REFRESH_TOKEN_AUTH",
                    AuthParameters={"REFRESH_TOKEN": refresh},
                )
                self._store(resp["AuthenticationResult"])
            return {"authorization": f"Bearer {self._id_token}"}


class ApiClient:
    def __init__(self, base_url: str, auth: Auth, timeout: float = 15.0, transport: httpx.BaseTransport | None = None):
        self.auth = auth
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)
        self.uploader = httpx.Client(timeout=60.0, transport=transport)

    def close(self) -> None:
        self.http.close()
        self.uploader.close()

    def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        resp = self.http.post(path, json=body, headers=self.auth.headers())
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        return resp

    def presign_upload(self, capture_id: str, content_type: str) -> dict[str, Any]:
        return self._post("/uploads", {"capture_id": capture_id, "content_type": content_type}).json()

    def upload_file(self, capture_id: str, path: str | Path, content_type: str) -> str:
        """Presign then PUT the file; returns the s3_key."""
        presigned = self.presign_upload(capture_id, content_type)
        data = Path(path).read_bytes()
        resp = self.uploader.put(presigned["url"], content=data, headers=presigned.get("headers") or {})
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        return presigned["s3_key"]

    def post_captures(self, captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._post("/captures", {"captures": captures}).json()["results"]

    def get_me(self) -> dict[str, Any]:
        resp = self.http.get("/me", headers=self.auth.headers())
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        return resp.json()
