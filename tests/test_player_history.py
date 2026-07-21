import os
import unittest

# swee.config reads required settings from the environment at import time; player_history.py
# imports it (and swee.rest_client), so stub the env before importing, same as test_releases.py.
os.environ.setdefault("DISCORD_BOT_TOKEN", "x")
os.environ.setdefault("GUILD_ID", "1")
os.environ.setdefault("ADMIN_ROLE_ID", "1")
os.environ.setdefault("RELAY_CHANNEL_ID", "1")
os.environ.setdefault("STATS_CHANNEL_ID", "1")
os.environ.setdefault("ACTIVITY_CHANNEL_ID", "1")
os.environ.setdefault("ALERTS_CHANNEL_ID", "1")
os.environ.setdefault("ADMIN_CHANNEL_ID", "1")
os.environ.setdefault("COMMANDS_CHANNEL_ID", "1")
os.environ.setdefault("BOT_UPDATES_CHANNEL_ID", "1")
os.environ.setdefault("REST_HOST", "x")
os.environ.setdefault("REST_PORT", "1")
os.environ.setdefault("REST_USER", "x")
os.environ.setdefault("REST_PASSWORD", "x")
os.environ.setdefault("PALWORLD_SETTINGS_INI_PATH", "/tmp/x")
os.environ.setdefault("PALWORLD_INSTALL_DIR", "/tmp")

from swee.player_history import player_history, resolve_owner_name  # noqa: E402


class ResolveOwnerNameTests(unittest.TestCase):
    def setUp(self):
        player_history.clear()

    def tearDown(self):
        player_history.clear()

    def test_resolves_dashed_lowercase_guid_to_name(self):
        player_history["steam_1"] = {
            "name": "Kippei",
            "last_seen": "2026-07-20T00:00:00-07:00",
            "player_id": "97398A79000000000000000000000000",
        }
        self.assertEqual(resolve_owner_name("97398a79-0000-0000-0000-000000000000"), "Kippei")

    def test_returns_none_for_unknown_guid(self):
        player_history["steam_1"] = {
            "name": "Kippei",
            "last_seen": "2026-07-20T00:00:00-07:00",
            "player_id": "97398A79000000000000000000000000",
        }
        self.assertIsNone(resolve_owner_name("00000000-0000-0000-0000-000000000000"))

    def test_returns_none_for_none_input(self):
        self.assertIsNone(resolve_owner_name(None))

    def test_returns_none_when_no_players_tracked(self):
        self.assertIsNone(resolve_owner_name("97398a79-0000-0000-0000-000000000000"))

    def test_ignores_entries_missing_player_id(self):
        # Entries written before this feature existed (or by record_leave for a player never
        # seen by record_join/refresh_online_players post-upgrade) have no player_id key.
        player_history["steam_1"] = {"name": "Legacy", "last_seen": "2026-07-20T00:00:00-07:00"}
        self.assertIsNone(resolve_owner_name("97398a79-0000-0000-0000-000000000000"))


if __name__ == "__main__":
    unittest.main()
