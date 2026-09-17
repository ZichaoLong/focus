import unittest
from unittest.mock import patch

from bot.web_runtime.auth import WebAuthManager


class WebAuthManagerTests(unittest.TestCase):
    def test_bootstrap_is_single_use_and_rotates(self):
        rotated: list[str] = []
        auth = WebAuthManager(session_ttl_seconds=3600, on_bootstrap_rotated=rotated.append)
        original = auth.bootstrap_token

        session = auth.exchange_bootstrap(original)

        self.assertIsNotNone(session)
        self.assertNotEqual(auth.bootstrap_token, original)
        self.assertEqual(rotated, [auth.bootstrap_token])
        self.assertIsNone(auth.exchange_bootstrap(original))
        self.assertEqual(auth.authenticate(session.session_token), session)

    def test_revoke_invalidates_session(self):
        auth = WebAuthManager(session_ttl_seconds=3600)
        session = auth.exchange_bootstrap(auth.bootstrap_token)
        self.assertIsNotNone(session)

        self.assertTrue(auth.revoke(session.session_token))
        self.assertIsNone(auth.authenticate(session.session_token))

    def test_local_and_external_sessions_retain_distinct_audiences(self):
        auth = WebAuthManager(session_ttl_seconds=3600)
        local = auth.exchange_bootstrap(auth.bootstrap_token)
        external = auth.issue_external_session(
            external_origin="https://focus.example.test",
            proxy_identity="proxy:user@example.test",
        )

        self.assertIsNotNone(local)
        self.assertIsNotNone(external)
        assert local is not None
        assert external is not None
        self.assertEqual(local.audience.kind, "local")
        self.assertEqual(external.audience.kind, "external")
        self.assertEqual(
            external.audience.external_origin,
            "https://focus.example.test",
        )
        self.assertEqual(
            external.audience.proxy_identity,
            "proxy:user@example.test",
        )
        self.assertEqual(auth.authenticate(external.session_token), external)

    def test_external_session_issuance_has_a_fixed_process_bound(self):
        auth = WebAuthManager(session_ttl_seconds=3600)
        sessions = [
            auth.issue_external_session(
                external_origin="https://focus.example.test",
                proxy_identity=f"proxy:user-{index}",
            )
            for index in range(128)
        ]

        self.assertTrue(all(session is not None for session in sessions))
        self.assertIsNone(
            auth.issue_external_session(
                external_origin="https://focus.example.test",
                proxy_identity="proxy:overflow",
            )
        )
        first = sessions[0]
        assert first is not None
        self.assertTrue(auth.revoke(first.session_token))
        self.assertIsNotNone(
            auth.issue_external_session(
                external_origin="https://focus.example.test",
                proxy_identity="proxy:replacement",
            )
        )

    def test_failed_rotation_persistence_keeps_old_bootstrap_valid(self):
        attempts: list[str] = []

        def persist(token: str) -> None:
            attempts.append(token)
            if len(attempts) == 1:
                raise OSError("disk full")

        auth = WebAuthManager(session_ttl_seconds=3600, on_bootstrap_rotated=persist)
        original = auth.bootstrap_token

        with self.assertRaisesRegex(OSError, "disk full"):
            auth.exchange_bootstrap(original)

        self.assertEqual(auth.bootstrap_token, original)
        session = auth.exchange_bootstrap(original)
        self.assertIsNotNone(session)
        self.assertNotEqual(auth.bootstrap_token, original)
        self.assertEqual(attempts[-1], auth.bootstrap_token)

    def test_rotation_callback_runs_outside_state_lock(self):
        observed: list[str] = []
        auth: WebAuthManager

        def persist(_token: str) -> None:
            observed.append(auth.bootstrap_token)

        auth = WebAuthManager(session_ttl_seconds=3600, on_bootstrap_rotated=persist)
        original = auth.bootstrap_token

        self.assertIsNotNone(auth.exchange_bootstrap(original))
        self.assertEqual(observed, [original])

    def test_renewal_slides_idle_deadline_without_rotating_capabilities(self):
        with patch("bot.web_runtime.auth.time.time", return_value=100.0) as clock:
            auth = WebAuthManager(
                session_ttl_seconds=60,
                session_max_lifetime_seconds=300,
            )
            session = auth.exchange_bootstrap(auth.bootstrap_token)
            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(session.expires_at, 160.0)
            self.assertEqual(session.absolute_expires_at, 400.0)

            clock.return_value = 130.0
            renewed = auth.renew_if_live(session.session_token)

            self.assertIsNotNone(renewed)
            assert renewed is not None
            self.assertEqual(renewed.session_token, session.session_token)
            self.assertEqual(renewed.csrf_token, session.csrf_token)
            self.assertEqual(renewed.expires_at, 190.0)
            self.assertEqual(renewed.absolute_expires_at, 400.0)

            # A task waking at the old deadline observes the authoritative
            # renewal instead of revoking the session it captured earlier.
            clock.return_value = 160.0
            self.assertEqual(auth.expire_if_due(session.session_token), renewed)
            clock.return_value = 190.0
            self.assertIsNone(auth.expire_if_due(session.session_token))

    def test_renewal_is_capped_and_cannot_revive_expired_or_revoked_session(self):
        with patch("bot.web_runtime.auth.time.time", return_value=100.0) as clock:
            auth = WebAuthManager(
                session_ttl_seconds=60,
                session_max_lifetime_seconds=180,
            )
            session = auth.exchange_bootstrap(auth.bootstrap_token)
            self.assertIsNotNone(session)
            assert session is not None

            for active_at in (150.0, 200.0):
                clock.return_value = active_at
                self.assertIsNotNone(auth.renew_if_live(session.session_token))
            clock.return_value = 250.0
            capped = auth.renew_if_live(session.session_token)
            self.assertIsNotNone(capped)
            assert capped is not None
            self.assertEqual(capped.expires_at, 280.0)
            self.assertEqual(capped.absolute_expires_at, 280.0)

            clock.return_value = 280.0
            self.assertIsNone(auth.renew_if_live(session.session_token))
            self.assertIsNone(auth.authenticate(session.session_token))

            replacement = auth.issue_external_session(
                external_origin="https://focus.example.test",
                proxy_identity="proxy:user",
            )
            self.assertIsNotNone(replacement)
            assert replacement is not None
            self.assertTrue(auth.revoke(replacement.session_token))
            self.assertIsNone(auth.renew_if_live(replacement.session_token))


if __name__ == "__main__":
    unittest.main()
