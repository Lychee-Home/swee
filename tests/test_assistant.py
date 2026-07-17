import time
import unittest

from swee.assistant import is_on_cooldown, parse_mention, record_answered


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
