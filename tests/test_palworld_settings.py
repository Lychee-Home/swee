import os
import tempfile
import unittest

from swee.palworld_settings import (
    parse_palworld_settings,
    render_option_settings,
    visible_settings,
    write_palworld_setting,
)

SAMPLE_INI = (
    '[/Script/Pal.PalGameWorldSettings]\n'
    'OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,'
    'ServerName="My Server",bIsPvP=False,'
    'AdminPassword="secret",ServerDescription="Hello, world")\n'
)


class RenderOptionSettingsTests(unittest.TestCase):
    def test_round_trips_parsed_pairs(self):
        pairs = {"Difficulty": "None", "DayTimeSpeedRate": "1.000000", "ServerName": '"My Server"'}
        self.assertEqual(
            render_option_settings(pairs),
            'Difficulty=None,DayTimeSpeedRate=1.000000,ServerName="My Server"',
        )


class WritePalworldSettingTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        with open(self.path, "w") as f:
            f.write(SAMPLE_INI)

    def tearDown(self):
        os.remove(self.path)

    def test_updates_only_target_key(self):
        write_palworld_setting(self.path, "bIsPvP", "True")
        pairs = parse_palworld_settings(self.path)
        self.assertEqual(pairs["bIsPvP"], "True")
        self.assertEqual(pairs["Difficulty"], "None")
        self.assertEqual(pairs["ServerName"], '"My Server"')
        self.assertEqual(pairs["ServerDescription"], '"Hello, world"')

    def test_preserves_surrounding_file_content(self):
        write_palworld_setting(self.path, "Difficulty", "Hard")
        with open(self.path) as f:
            content = f.read()
        self.assertTrue(content.startswith("[/Script/Pal.PalGameWorldSettings]\n"))
        self.assertTrue(content.endswith("\n"))


class VisibleSettingsTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        with open(self.path, "w") as f:
            f.write(SAMPLE_INI)

    def tearDown(self):
        os.remove(self.path)

    def test_omits_redacted_keys(self):
        settings = visible_settings(self.path)
        self.assertNotIn("AdminPassword", settings)
        self.assertEqual(settings["Difficulty"], "None")


if __name__ == "__main__":
    unittest.main()
