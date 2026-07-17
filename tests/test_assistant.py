import os
import time
import unittest

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

from swee.assistant import is_on_cooldown, parse_mention, record_answered, fuzzy_match_pal_name


class ParseMentionTests(unittest.TestCase):
    def test_extracts_question_after_prefix(self):
        self.assertEqual(parse_mention("@swee what does lamball drop?"), "what does lamball drop?")

    def test_case_insensitive_prefix(self):
        self.assertEqual(parse_mention("@SWEE what does lamball drop?"), "what does lamball drop?")

    def test_ignores_non_mention_messages(self):
        self.assertIsNone(parse_mention("dam they fr made a lot of good pals"))

    def test_returns_none_for_empty_question(self):
        self.assertIsNone(parse_mention("@swee"))
        self.assertIsNone(parse_mention("@swee   "))

    def test_requires_word_boundary_after_prefix(self):
        self.assertIsNone(parse_mention("@sweetalk something"))


class CooldownTests(unittest.TestCase):
    def test_not_on_cooldown_when_never_answered(self):
        self.assertFalse(is_on_cooldown("Kippei", {}, 30, time.monotonic()))

    def test_on_cooldown_within_window(self):
        last_answered = {"Kippei": 100.0}
        self.assertTrue(is_on_cooldown("Kippei", last_answered, 30, 110.0))

    def test_not_on_cooldown_after_window(self):
        last_answered = {"Kippei": 100.0}
        self.assertFalse(is_on_cooldown("Kippei", last_answered, 30, 131.0))

    def test_record_answered_sets_timestamp(self):
        last_answered = {}
        record_answered("Kippei", last_answered, 42.0)
        self.assertEqual(last_answered["Kippei"], 42.0)


class FuzzyMatchPalNameTests(unittest.TestCase):
    KNOWN = ["Lamball", "Cattiva", "Direhowl", "Anubis"]

    def test_exact_match_case_insensitive(self):
        self.assertEqual(fuzzy_match_pal_name("lamball", self.KNOWN), "Lamball")

    def test_close_typo_match(self):
        self.assertEqual(fuzzy_match_pal_name("lambal", self.KNOWN), "Lamball")

    def test_no_match_returns_none(self):
        self.assertIsNone(fuzzy_match_pal_name("xyzzyzzy", self.KNOWN))

    def test_empty_known_names_returns_none(self):
        self.assertIsNone(fuzzy_match_pal_name("lamball", []))
