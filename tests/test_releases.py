import os
import unittest

# swee.config reads required settings from the environment at import time; releases.py imports
# it for GITHUB_REPO/etc, so stub the env before importing, same as any other config consumer.
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

from datetime import datetime, timezone  # noqa: E402

from swee.releases import (  # noqa: E402
    humanize_release_notes,
    parse_release_header,
    parse_release_timestamp,
    select_missed_releases,
)

RELEASE_PLEASE_BODY = (
    "## [2.5.0](https://github.com/Lychee-Home/swee/compare/v2.4.0...v2.5.0) (2026-07-17)\n"
    "\n"
    "\n"
    "### Features\n"
    "\n"
    "* broadcast in-game warning and delay before /restart and /update "
    "([#31](https://github.com/Lychee-Home/swee/issues/31)) "
    "([d8bc002](https://github.com/Lychee-Home/swee/commit/d8bc0024a9da15c8d50aefb8e2d7ba993b797606))\n"
    "* make GITHUB_REPO optional "
    "([#29](https://github.com/Lychee-Home/swee/issues/29)) "
    "([8d6d6ff](https://github.com/Lychee-Home/swee/commit/8d6d6ff2f4bd4f6c3146c9eac70470e716459ed8))\n"
    "\n"
    "\n"
    "### Bug Fixes\n"
    "\n"
    "* add fallback join notification for missed 'joined the server' log lines "
    "([#33](https://github.com/Lychee-Home/swee/issues/33)) "
    "([b41369d](https://github.com/Lychee-Home/swee/commit/b41369da8322621296885d5ab91888fe5a0250b7))\n"
)


class HumanizeReleaseNotesTests(unittest.TestCase):
    def test_strips_pr_and_commit_links_from_release_please_body(self):
        notes = humanize_release_notes(RELEASE_PLEASE_BODY)
        self.assertNotIn("http", notes)
        self.assertNotIn("#31", notes)
        self.assertNotIn("d8bc002", notes)

    def test_groups_features_and_fixes_under_labeled_sections(self):
        notes = humanize_release_notes(RELEASE_PLEASE_BODY)
        self.assertEqual(
            notes,
            "**2.5.0**\n"
            "\n"
            "**New**\n"
            "• Broadcast in-game warning and delay before /restart and /update\n"
            "\n"
            "**Fixes**\n"
            "• Add fallback join notification for missed 'joined the server' log lines",
        )

    def test_bullet_mentioning_env_var_is_dropped(self):
        notes = humanize_release_notes(RELEASE_PLEASE_BODY)
        self.assertNotIn("GITHUB_REPO", notes)

    def test_section_with_only_env_var_bullets_is_omitted_entirely(self):
        body = "### Features\n\n* make GITHUB_REPO optional\n"
        self.assertIsNone(humanize_release_notes(body))

    def test_bullet_without_link_suffix_is_still_parsed(self):
        body = "### Features\n\n* some manually written bullet\n"
        self.assertEqual(humanize_release_notes(body), "**New**\n• Some manually written bullet")

    def test_unrecognized_section_is_ignored(self):
        body = "### Miscellaneous\n\n* something not categorized\n"
        self.assertIsNone(humanize_release_notes(body))

    def test_returns_none_for_body_with_no_bullets(self):
        self.assertIsNone(humanize_release_notes("## [2.5.0](url) (2026-07-17)\n\nNothing here.\n"))


class SelectMissedReleasesTests(unittest.TestCase):
    def test_returns_releases_after_last_tag_oldest_first(self):
        releases = [
            {"tag_name": "v2.5.2", "body": "c"},
            {"tag_name": "v2.5.1", "body": "b"},
            {"tag_name": "v2.5.0", "body": "a"},
        ]
        missed = select_missed_releases(releases, "v2.5.0")
        self.assertEqual([r["tag_name"] for r in missed], ["v2.5.1", "v2.5.2"])

    def test_returns_empty_list_when_last_tag_is_newest(self):
        releases = [{"tag_name": "v2.5.0", "body": "a"}]
        self.assertEqual(select_missed_releases(releases, "v2.5.0"), [])

    def test_treats_all_releases_as_missed_when_last_tag_not_found(self):
        releases = [
            {"tag_name": "v2.5.2", "body": "c"},
            {"tag_name": "v2.5.1", "body": "b"},
        ]
        missed = select_missed_releases(releases, "v2.4.0")
        self.assertEqual([r["tag_name"] for r in missed], ["v2.5.1", "v2.5.2"])

    def test_returns_empty_list_for_empty_releases(self):
        self.assertEqual(select_missed_releases([], "v2.5.0"), [])


class ParseReleaseHeaderTests(unittest.TestCase):
    def test_parses_linked_version_and_date(self):
        version, date = parse_release_header(RELEASE_PLEASE_BODY)
        self.assertEqual(version, "2.5.0")
        self.assertEqual(date, datetime(2026, 7, 17, tzinfo=timezone.utc))

    def test_parses_plain_version_with_no_compare_link(self):
        version, date = parse_release_header("## 1.0.0 (2026-01-01)\n\n### Features\n\n* first release\n")
        self.assertEqual(version, "1.0.0")
        self.assertEqual(date, datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_returns_none_none_when_header_absent(self):
        self.assertEqual(parse_release_header("no header here\n"), (None, None))


class ParseReleaseTimestampTests(unittest.TestCase):
    def test_parses_github_published_at(self):
        self.assertEqual(
            parse_release_timestamp("2026-07-17T10:00:00Z"),
            datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc),
        )

    def test_returns_none_when_missing(self):
        self.assertIsNone(parse_release_timestamp(None))
        self.assertIsNone(parse_release_timestamp(""))


if __name__ == "__main__":
    unittest.main()
