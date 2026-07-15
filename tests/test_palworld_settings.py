import os
import tempfile
import unittest

from swee.palworld_settings import (
    classify_value,
    format_new_value,
    parse_palworld_settings,
    render_option_settings,
    visible_settings,
    write_palworld_setting,
)

SAMPLE_INI = (
    '[/Script/Pal.PalGameWorldSettings]\n'
    'OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,'
    'ServerName="My Server",bIsPvP=False,'
    'CrossplayPlatforms=(Steam,Xbox,PS5,Mac),'
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
        self.assertEqual(pairs["CrossplayPlatforms"], "(Steam,Xbox,PS5,Mac)")

    def test_parses_parenthesized_list_value_as_one_key(self):
        pairs = parse_palworld_settings(self.path)
        self.assertEqual(pairs["CrossplayPlatforms"], "(Steam,Xbox,PS5,Mac)")
        self.assertNotIn("Xbox", pairs)
        self.assertNotIn("PS5", pairs)
        self.assertNotIn("Mac)", pairs)

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


class ClassifyValueTests(unittest.TestCase):
    def test_bool(self):
        self.assertEqual(classify_value("True"), "bool")
        self.assertEqual(classify_value("False"), "bool")

    def test_number(self):
        self.assertEqual(classify_value("1.000000"), "number")
        self.assertEqual(classify_value("-5"), "number")

    def test_string(self):
        self.assertEqual(classify_value('"My Server"'), "string")

    def test_token(self):
        self.assertEqual(classify_value("None"), "token")

    def test_list(self):
        self.assertEqual(classify_value("(Steam,Xbox,PS5,Mac)"), "list")


class FormatNewValueTests(unittest.TestCase):
    def test_bool_accepts_case_insensitive(self):
        self.assertEqual(format_new_value("False", "true"), "True")
        self.assertEqual(format_new_value("True", "FALSE"), "False")

    def test_bool_rejects_non_bool(self):
        with self.assertRaises(ValueError):
            format_new_value("True", "1")

    def test_number_accepts_number(self):
        self.assertEqual(format_new_value("1.000000", "2.5"), "2.5")

    def test_number_rejects_non_number(self):
        with self.assertRaises(ValueError):
            format_new_value("1.000000", "abc")

    def test_string_wraps_in_quotes(self):
        self.assertEqual(format_new_value('"My Server"', "New Name"), '"New Name"')

    def test_string_rejects_embedded_quote(self):
        with self.assertRaises(ValueError):
            format_new_value('"My Server"', 'bad "name"')

    def test_token_accepts_bare_word(self):
        self.assertEqual(format_new_value("None", "Hard"), "Hard")

    def test_token_rejects_spaces(self):
        with self.assertRaises(ValueError):
            format_new_value("None", "not valid")

    def test_category_switch_rejected(self):
        with self.assertRaises(ValueError):
            format_new_value("1.000000", "True")

    def test_string_rejects_newline(self):
        with self.assertRaises(ValueError):
            format_new_value('"My Server"', "line1\nline2")

    def test_token_rejects_newline(self):
        with self.assertRaises(ValueError):
            format_new_value("None", "line1\nline2")

    def test_list_wraps_in_parens(self):
        self.assertEqual(
            format_new_value("(Steam,Xbox,PS5,Mac)", "Steam,Xbox"),
            "(Steam,Xbox)",
        )

    def test_list_rejects_parens_in_input(self):
        with self.assertRaises(ValueError):
            format_new_value("(Steam,Xbox,PS5,Mac)", "Steam,(Xbox)")

    def test_list_rejects_newline(self):
        with self.assertRaises(ValueError):
            format_new_value("(Steam,Xbox,PS5,Mac)", "Steam,\nXbox")


if __name__ == "__main__":
    unittest.main()
