import unittest

from swee.uptime import format_uptime


class FormatUptimeTests(unittest.TestCase):
    def test_minutes_only(self):
        self.assertEqual(format_uptime(5 * 60), "5m")

    def test_hours_with_remainder_minutes(self):
        self.assertEqual(format_uptime(5 * 3600), "5h")

    def test_hours_with_no_remainder_minutes(self):
        self.assertEqual(format_uptime(5 * 3600 + 0 * 60), "5h")

    def test_hours_with_minutes_remainder(self):
        self.assertEqual(format_uptime(1 * 3600 + 3 * 60), "1h 3m")

    def test_days_with_hours_remainder(self):
        self.assertEqual(format_uptime(1 * 86400 + 3 * 3600), "1d 3h")

    def test_days_with_no_remainder(self):
        self.assertEqual(format_uptime(3 * 86400), "3d")

    def test_weeks_with_days_remainder(self):
        self.assertEqual(format_uptime(2 * (7 * 86400) + 1 * 86400), "2w 1d")

    def test_weeks_with_no_remainder(self):
        self.assertEqual(format_uptime(3 * (7 * 86400)), "3w")

    def test_months_with_days_remainder(self):
        self.assertEqual(format_uptime(1 * (30 * 86400) + 3 * 86400), "1mo 3d")

    def test_months_with_no_remainder(self):
        self.assertEqual(format_uptime(2 * (30 * 86400)), "2mo")


if __name__ == "__main__":
    unittest.main()
