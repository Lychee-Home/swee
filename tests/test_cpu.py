import unittest

from swee.cpu import compute_cpu_pct


class ComputeCpuPctTests(unittest.TestCase):
    def test_fully_idle_between_samples(self):
        # idle grows by exactly the same amount as total -> 0% busy
        line1 = "cpu  0 0 0 1000 0 0 0 0 0 0"
        line2 = "cpu  0 0 0 2000 0 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 0)

    def test_fully_busy_between_samples(self):
        # user time grows, idle stays flat -> 100% busy
        line1 = "cpu  1000 0 0 5000 0 0 0 0 0 0"
        line2 = "cpu  2000 0 0 5000 0 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 100)

    def test_partial_busy_between_samples(self):
        # total grows by 1000, idle grows by 250 -> 75% busy
        line1 = "cpu  0 0 0 1000 0 0 0 0 0 0"
        line2 = "cpu  750 0 0 1250 0 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 75)

    def test_iowait_counts_as_idle(self):
        # all growth is iowait (index 4) -> counts as idle, 0% busy
        line1 = "cpu  0 0 0 1000 0 0 0 0 0 0"
        line2 = "cpu  0 0 0 1000 500 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 0)

    def test_zero_total_delta_returns_zero(self):
        # identical samples (e.g. clock hasn't ticked) -> avoid division by zero
        line1 = "cpu  100 0 0 900 0 0 0 0 0 0"
        line2 = "cpu  100 0 0 900 0 0 0 0 0 0"
        self.assertEqual(compute_cpu_pct(line1, line2), 0)


if __name__ == "__main__":
    unittest.main()
