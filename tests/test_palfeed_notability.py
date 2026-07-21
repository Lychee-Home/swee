import unittest

from swee.palfeed_notability import notability_tier, talent_score


class TalentScoreTests(unittest.TestCase):
    def test_sums_all_three_talents(self):
        event = {"talent_hp": 100, "talent_shot": 90, "talent_defense": 80}
        self.assertEqual(talent_score(event), 270)

    def test_missing_talent_fields_default_to_zero(self):
        self.assertEqual(talent_score({}), 0)


class NotabilityTierTests(unittest.TestCase):
    def test_rare_pal_is_lucky_regardless_of_talent(self):
        event = {"is_rare_pal": True, "talent_hp": 0, "talent_shot": 0, "talent_defense": 0}
        self.assertEqual(notability_tier(event), "Lucky")

    def test_awakening_is_awakened_regardless_of_talent(self):
        event = {"is_awakening": True, "talent_hp": 0, "talent_shot": 0, "talent_defense": 0}
        self.assertEqual(notability_tier(event), "Awakened")

    def test_rare_pal_takes_priority_over_awakening(self):
        event = {"is_rare_pal": True, "is_awakening": True}
        self.assertEqual(notability_tier(event), "Lucky")

    def test_perfect_talent_score(self):
        event = {"talent_hp": 100, "talent_shot": 100, "talent_defense": 100}
        self.assertEqual(notability_tier(event), "Perfect")

    def test_excellent_talent_score(self):
        event = {"talent_hp": 100, "talent_shot": 90, "talent_defense": 90}
        self.assertEqual(notability_tier(event), "Excellent")

    def test_great_talent_score(self):
        event = {"talent_hp": 90, "talent_shot": 80, "talent_defense": 80}
        self.assertEqual(notability_tier(event), "Great")

    def test_below_all_thresholds_is_not_notable(self):
        event = {"talent_hp": 50, "talent_shot": 50, "talent_defense": 50}
        self.assertEqual(notability_tier(event), "")

    def test_boundary_just_below_great_threshold(self):
        event = {"talent_hp": 83, "talent_shot": 83, "talent_defense": 83}  # sums to 249
        self.assertEqual(notability_tier(event), "")


if __name__ == "__main__":
    unittest.main()
