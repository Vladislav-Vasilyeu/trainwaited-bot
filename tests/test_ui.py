import unittest
from datetime import date

from ui import date_calendar_keyboard, station_suggestions_keyboard


class StationSuggestionKeyboardTests(unittest.TestCase):
    def test_station_results_are_paginated_without_losing_selection_indexes(self):
        suggestions = [
            {"label": f"Station {index}", "value": f"value-{index}", "exp": str(index)}
            for index in range(10)
        ]

        first_page = station_suggestions_keyboard(suggestions, "from", "a1b2c3d4")
        second_page = station_suggestions_keyboard(
            suggestions, "from", "a1b2c3d4", page=1
        )

        first_callbacks = [
            button.callback_data
            for row in first_page.inline_keyboard
            for button in row
        ]
        second_callbacks = [
            button.callback_data
            for row in second_page.inline_keyboard
            for button in row
        ]
        self.assertIn("from_pick_a1b2c3d4_0", first_callbacks)
        self.assertIn("from_pick_a1b2c3d4_7", first_callbacks)
        self.assertNotIn("from_pick_a1b2c3d4_8", first_callbacks)
        self.assertIn("from_pick_a1b2c3d4_8", second_callbacks)
        self.assertIn("from_pick_a1b2c3d4_9", second_callbacks)
        self.assertIn("from_page_a1b2c3d4_1", first_callbacks)
        self.assertIn("from_page_a1b2c3d4_0", second_callbacks)


class DateCalendarKeyboardTests(unittest.TestCase):
    def test_calendar_only_offers_today_or_future_dates(self):
        today = date(2026, 10, 26)
        calendar = date_calendar_keyboard(2026, 10, today)
        callbacks = [
            button.callback_data
            for row in calendar.inline_keyboard
            for button in row
        ]
        selected_dates = [
            date.fromisoformat(callback.removeprefix("date_pick_"))
            for callback in callbacks
            if callback.startswith("date_pick_")
        ]

        self.assertIn("date_pick_2026-10-26", callbacks)
        self.assertNotIn("date_pick_2026-10-25", callbacks)
        self.assertTrue(all(selected >= today for selected in selected_dates))
        self.assertEqual(calendar.inline_keyboard[0][0].callback_data, "date_disabled")

    def test_calendar_month_navigation_handles_year_boundaries(self):
        today = date(2026, 12, 15)
        december = date_calendar_keyboard(2026, 12, today)
        january = date_calendar_keyboard(2027, 1, today)

        self.assertEqual(december.inline_keyboard[0][2].callback_data, "date_next_2026-12")
        self.assertEqual(january.inline_keyboard[0][0].callback_data, "date_prev_2027-01")


if __name__ == "__main__":
    unittest.main()
