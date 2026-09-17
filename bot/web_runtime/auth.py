"""Short-lived browser authentication for the local Focus Web Gateway."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Literal


_MAX_EXTERNAL_SESSIONS = 128


@dataclass(slots=True, frozen=True)
class WebAuthAudience:
    kind: Literal["local", "external"]
    external_origin: str = ""
    proxy_identity: str = ""


LOCAL_WEB_AUTH_AUDIENCE = WebAuthAudience(kind="local")


@dataclass(slots=True, frozen=True)
class WebAuthSession:
    session_token: str
    csrf_token: str
    expires_at: float
    absolute_expires_at: float
    audience: WebAuthAudience = LOCAL_WEB_AUTH_AUDIENCE


class WebAuthManager:
    def __init__(
        self,
        *,
        session_ttl_seconds: float,
        session_max_lifetime_seconds: float = 7 * 24 * 60 * 60,
        on_bootstrap_rotated: Callable[[str], None] | None = None,
    ) -> None:
        self._session_ttl_seconds = max(float(session_ttl_seconds), 60.0)
        self._session_max_lifetime_seconds = max(
            float(session_max_lifetime_seconds),
            self._session_ttl_seconds,
        )
        self._on_bootstrap_rotated = on_bootstrap_rotated
        self._lock = threading.Lock()
        self._exchange_lock = threading.Lock()
        self._bootstrap_token = secrets.token_urlsafe(32)
        self._sessions: dict[str, WebAuthSession] = {}

    @property
    def bootstrap_token(self) -> str:
        with self._lock:
            return self._bootstrap_token

    def exchange_bootstrap(self, token: str) -> WebAuthSession | None:
        normalized = str(token or "").strip()
        if not normalized:
            return None
        with self._exchange_lock:
            with self._lock:
                self._prune_expired_locked()
                if not secrets.compare_digest(normalized, self._bootstrap_token):
                    return None
                now = time.time()
                absolute_expires_at = now + self._session_max_lifetime_seconds
                session = WebAuthSession(
                    session_token=secrets.token_urlsafe(32),
                    csrf_token=secrets.token_urlsafe(24),
                    expires_at=min(
                        now + self._session_ttl_seconds,
                        absolute_expires_at,
                    ),
                    absolute_expires_at=absolute_expires_at,
                    audience=LOCAL_WEB_AUTH_AUDIENCE,
                )
                rotated = secrets.token_urlsafe(32)
            # Persist the replacement capability before committing either the
            # in-memory rotation or its authenticated session.  A failed
            # persistence callback leaves the old bootstrap token usable, so
            # focusctl can retry instead of stranding the running gateway.
            if self._on_bootstrap_rotated is not None:
                self._on_bootstrap_rotated(rotated)
            with self._lock:
                self._bootstrap_token = rotated
                self._sessions[session.session_token] = session
                return session

    def issue_external_session(
        self,
        *,
        external_origin: str,
        proxy_identity: str,
    ) -> WebAuthSession | None:
        origin = str(external_origin or "").strip()
        identity = str(proxy_identity or "").strip()
        if not origin or not identity:
            return None
        audience = WebAuthAudience(
            kind="external",
            external_origin=origin,
            proxy_identity=identity,
        )
        with self._lock:
            self._prune_expired_locked()
            external_count = sum(
                session.audience.kind == "external"
                for session in self._sessions.values()
            )
            if external_count >= _MAX_EXTERNAL_SESSIONS:
                return None
            now = time.time()
            absolute_expires_at = now + self._session_max_lifetime_seconds
            session = WebAuthSession(
                session_token=secrets.token_urlsafe(32),
                csrf_token=secrets.token_urlsafe(24),
                expires_at=min(
                    now + self._session_ttl_seconds,
                    absolute_expires_at,
                ),
                absolute_expires_at=absolute_expires_at,
                audience=audience,
            )
            self._sessions[session.session_token] = session
            return session

    def authenticate(self, session_token: str) -> WebAuthSession | None:
        normalized = str(session_token or "").strip()
        if not normalized:
            return None
        with self._lock:
            self._prune_expired_locked()
            return self._sessions.get(normalized)

    def renew_if_live(self, session_token: str) -> WebAuthSession | None:
        """Atomically extend one live session without rotating its capabilities."""

        normalized = str(session_token or "").strip()
        if not normalized:
            return None
        with self._lock:
            now = time.time()
            session = self._sessions.get(normalized)
            if session is None:
                return None
            if session.expires_at <= now or session.absolute_expires_at <= now:
                self._sessions.pop(normalized, None)
                return None
            expires_at = max(
                session.expires_at,
                min(
                    now + self._session_ttl_seconds,
                    session.absolute_expires_at,
                ),
            )
            renewed = replace(session, expires_at=expires_at)
            self._sessions[normalized] = renewed
            return renewed

    def expire_if_due(self, session_token: str) -> WebAuthSession | None:
        """Remove a due session, or return its current authoritative deadline."""

        normalized = str(session_token or "").strip()
        if not normalized:
            return None
        with self._lock:
            session = self._sessions.get(normalized)
            if session is None:
                return None
            now = time.time()
            if session.expires_at <= now or session.absolute_expires_at <= now:
                self._sessions.pop(normalized, None)
                return None
            return session

    def revoke(self, session_token: str) -> bool:
        normalized = str(session_token or "").strip()
        if not normalized:
            return False
        with self._lock:
            return self._sessions.pop(normalized, None) is not None

    def _prune_expired_locked(self) -> None:
        now = time.time()
        for token, session in list(self._sessions.items()):
            if session.expires_at <= now or session.absolute_expires_at <= now:
                self._sessions.pop(token, None)
