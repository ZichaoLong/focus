"""Compatibility import for the Focus Web adapter.

The update owner lives with the installation authority so the running service
and the out-of-service worker share one journal and source validation path.
"""

from bot.installation.update import (  # noqa: F401
    DEFAULT_SOURCE as DEFAULT_UPDATE_SOURCE_URL,
    FocusUpdateController,
    UpdateError as FocusUpdateError,
    validate_commit,
    validate_source as validate_update_source_url,
)

UPDATE_STATES = frozenset({"idle", "checking", "ready", "applying", "succeeded", "failed", "unknown"})
