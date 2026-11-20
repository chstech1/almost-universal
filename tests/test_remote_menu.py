"""Regression checks for navigation and temperature adjustments."""

from copy import deepcopy
import unittest

from custom_components.ununiversal_remote.menu import (
    SAMPLE_MENU,
    resolve_press,
    screen_payload,
    temperature_change,
    validate_menu,
)


class TestMenu(unittest.TestCase):
    def test_same_button_depends_on_screen(self):
        draft = deepcopy(SAMPLE_MENU)
        draft["screens"]["tv"]["buttons"]["soft_4"]["effect"] = {
            "kind": "script", "target": "script.tv_shutdown",
        }
        menu = validate_menu(draft)
        self.assertEqual(resolve_press(menu, "activities", "soft_1"), ("tv", None))
        self.assertEqual(resolve_press(menu, "tv", "soft_2"), ("ac", None))
        self.assertEqual(resolve_press(menu, "ac", "soft_4"), ("tv", None))
        self.assertEqual(
            resolve_press(menu, "tv", "soft_4"),
            ("activities", {"kind": "script", "target": "script.tv_shutdown"}),
        )
        self.assertEqual(screen_payload(menu, "ac")["buttons"], {"soft_4": "Back"})

    def test_invalid_shortcut_and_link(self):
        for button, mapping in (
            ("soft_5", {"label": "Fifth key"}),
            ("soft_3", {"label": "Ghost", "next": "missing"}),
        ):
            with self.subTest(button=button):
                draft = deepcopy(SAMPLE_MENU)
                draft["screens"]["tv"]["buttons"][button] = mapping
                with self.assertRaises(ValueError):
                    validate_menu(draft)

    def test_thermostat_uses_confirmed_range_and_leaves_the_other_target(self):
        attrs = {"min_temp": 45, "max_temp": 95, "target_temp_step": 0.5,
                 "target_temp_low": 68, "target_temp_high": 70}
        first = temperature_change("heat_cool", attrs, "heat_up")
        self.assertEqual(first, {"target_temp_low": 68.5, "target_temp_high": 70})
        second = temperature_change("heat_cool", {**attrs, **first}, "heat_up")
        self.assertEqual(second["target_temp_low"], 69)
        self.assertEqual(
            temperature_change("heat_cool", {**attrs, "target_temp_low": 69.5}, "heat_up"),
            {},
        )
        self.assertEqual(temperature_change("cool", {**attrs, "temperature": 95}, "cool_up"), {})
        with self.assertRaises(ValueError):
            temperature_change("off", attrs, "heat_up")
