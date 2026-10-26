import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlparse

import scraper
from playwright.async_api import TimeoutError as PlaywrightTimeout
from scraper import (
    RailwayVerificationError,
    StationLookupError,
    _route_url,
    _wait_for_schedule,
    count_matching_seats,
    parse_station_suggestions,
)
from ui import parse_preference


class SeatFilterTests(unittest.TestCase):
    def setUp(self):
        self.seats = {
            "Нижние": 2,
            "Верхние": 3,
            "Нижние боковые": 4,
            "Верхние боковые": 5,
        }

    def test_lower_and_upper_filter_groups(self):
        self.assertEqual(count_matching_seats(self.seats, "lower"), 2)
        self.assertEqual(count_matching_seats(self.seats, "lower_any"), 6)
        self.assertEqual(count_matching_seats(self.seats, "upper"), 3)
        self.assertEqual(count_matching_seats(self.seats, "upper_any"), 8)

    def test_side_filters(self):
        self.assertEqual(count_matching_seats(self.seats, "lower_side"), 4)
        self.assertEqual(count_matching_seats(self.seats, "upper_side"), 5)
        self.assertEqual(count_matching_seats(self.seats, "side_any"), 9)

    def test_unknown_filter_does_not_match_everything(self):
        self.assertEqual(count_matching_seats(self.seats, "unknown"), 0)

    def test_unfiltered_count_includes_all_categories(self):
        self.assertEqual(count_matching_seats(self.seats, None), 14)


class RouteUrlTests(unittest.TestCase):
    def test_station_names_are_encoded_in_query(self):
        url = _route_url("Минск-Пассажирский", "Брест & вокзал", "2026-12-31")
        parsed = urlparse(url)
        self.assertEqual(parsed.netloc, "pass.rw.by")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "from": ["Минск-Пассажирский"],
                "to": ["Брест & вокзал"],
                "date": ["2026-12-31"],
            },
        )

    def test_selected_station_codes_are_included_in_route_query(self):
        url = _route_url(
            "Москва Белорусская",
            "Брест-Центральный",
            "2026-12-31",
            from_exp="2000006",
            to_exp="2100001",
        )
        self.assertEqual(
            parse_qs(urlparse(url).query),
            {
                "from": ["Москва Белорусская"],
                "to": ["Брест-Центральный"],
                "date": ["2026-12-31"],
                "from_exp": ["2000006"],
                "to_exp": ["2100001"],
            },
        )


class StationSuggestionTests(unittest.TestCase):
    def test_station_suggestions_keep_labels_values_and_station_codes(self):
        suggestions = parse_station_suggestions(
            [
                {
                    "label": "ст. Москва Белорусская, Россия",
                    "value": "Москва Белорусская",
                    "exp": "2000006",
                },
                {"label": "incomplete", "value": "incomplete"},
                None,
            ]
        )

        self.assertEqual(
            suggestions,
            [
                {
                    "label": "ст. Москва Белорусская, Россия",
                    "value": "Москва Белорусская",
                    "exp": "2000006",
                }
            ],
        )

    def test_invalid_suggestion_payload_is_reported(self):
        with self.assertRaises(StationLookupError):
            parse_station_suggestions({"unexpected": "payload"})


class SeatPreferenceCallbackTests(unittest.TestCase):
    def test_all_preferences_parse_without_truncating_filter_names(self):
        expected = {
            "pref_any_3": (None, None, "3"),
            "pref_platzkart_3": ("platzkart", None, "3"),
            "pref_coupe_3": ("coupe", None, "3"),
            "pref_lower_3": ("platzkart", "lower", "3"),
            "pref_lower_any_3": ("platzkart", "lower_any", "3"),
            "pref_upper_3": ("platzkart", "upper", "3"),
            "pref_upper_any_3": ("platzkart", "upper_any", "3"),
            "pref_lower_side_3": ("platzkart", "lower_side", "3"),
            "pref_upper_side_3": ("platzkart", "upper_side", "3"),
            "pref_side_any_3": ("platzkart", "side_any", "3"),
        }
        self.assertEqual(
            {callback: parse_preference(callback) for callback in expected},
            expected,
        )


class TicketCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_station_search_reads_suggestions_from_the_page_widget(self):
        page = AsyncMock()
        page.title.return_value = "Schedule"
        locator = AsyncMock()
        page.locator = Mock(return_value=locator)
        page.evaluate.return_value = [
            {
                "label": "ст. Москва Белорусская, Россия",
                "value": "Москва Белорусская",
                "exp": "2000006",
            }
        ]
        context = AsyncMock()
        context.new_page.return_value = page

        with patch.object(scraper, "get_context", new_callable=AsyncMock, return_value=context):
            results = await scraper.search_stations("Москва")

        self.assertEqual(results[0]["exp"], "2000006")
        page.locator.assert_called_once_with("#one-way-raspFormFromTitle")
        locator.fill.assert_awaited_once_with("Москва")
        page.wait_for_function.assert_awaited_once()
        page.close.assert_awaited_once()

    async def test_station_search_surfaces_verification_page(self):
        page = AsyncMock()
        page.title.return_value = "Verification"
        context = AsyncMock()
        context.new_page.return_value = page

        with patch.object(scraper, "get_context", new_callable=AsyncMock, return_value=context):
            with self.assertRaises(RailwayVerificationError):
                await scraper.search_stations("Москва")

        page.close.assert_awaited_once()

    async def test_ticket_check_reports_verification_as_page_error(self):
        page = AsyncMock()
        page.title.return_value = "Verification"
        context = AsyncMock()
        context.new_page.return_value = page

        with patch.object(scraper, "get_context", new_callable=AsyncMock, return_value=context):
            result = await scraper._check_tickets_sync(
                "unit-test-from",
                "unit-test-to",
                "2099-12-31",
                "unit-test-train",
                retries=1,
            )

        self.assertEqual(result["status"], "page_error")
        page.close.assert_awaited_once()

    async def test_verification_page_is_not_treated_as_an_empty_schedule(self):
        page = AsyncMock()
        page.title.return_value = "Verification"

        with self.assertRaises(RailwayVerificationError):
            await _wait_for_schedule(page)

        page.wait_for_selector.assert_not_awaited()

    async def test_verification_after_schedule_timeout_is_reported(self):
        page = AsyncMock()
        page.title.side_effect = ["Schedule", "Verification"]
        page.wait_for_selector.side_effect = PlaywrightTimeout("timed out")

        with self.assertRaises(RailwayVerificationError):
            await _wait_for_schedule(page)

        page.wait_for_selector.assert_awaited_once()

    async def test_error_result_is_returned_and_not_cached(self):
        error_result = {"status": "error", "url": "", "items": [], "seats": {}}
        with patch.object(
            scraper,
            "_check_tickets_sync",
            new_callable=AsyncMock,
            return_value=error_result,
        ) as check:
            first = await scraper.check_tickets(
                "unit-test-from", "unit-test-to", "2099-12-31", "unit-test-error"
            )
            second = await scraper.check_tickets(
                "unit-test-from", "unit-test-to", "2099-12-31", "unit-test-error"
            )

        self.assertEqual(first, error_result)
        self.assertEqual(second, error_result)
        self.assertEqual(check.await_count, 2)

    async def test_successful_empty_result_is_cached(self):
        empty_result = {"status": "no_tickets", "url": "", "items": [], "seats": {}}
        with patch.object(
            scraper,
            "_check_tickets_sync",
            new_callable=AsyncMock,
            return_value=empty_result,
        ) as check:
            first = await scraper.check_tickets(
                "unit-test-from", "unit-test-to", "2099-12-31", "unit-test-empty"
            )
            second = await scraper.check_tickets(
                "unit-test-from", "unit-test-to", "2099-12-31", "unit-test-empty"
            )

        self.assertEqual(first, empty_result)
        self.assertEqual(second, empty_result)
        self.assertEqual(check.await_count, 1)

    async def test_cache_separates_different_station_codes(self):
        empty_result = {"status": "no_tickets", "url": "", "items": [], "seats": {}}
        with patch.object(
            scraper,
            "_check_tickets_sync",
            new_callable=AsyncMock,
            return_value=empty_result,
        ) as check:
            await scraper.check_tickets(
                "unit-test-from",
                "unit-test-to",
                "2099-12-31",
                "unit-test-station-codes",
                from_exp="origin-a",
            )
            await scraper.check_tickets(
                "unit-test-from",
                "unit-test-to",
                "2099-12-31",
                "unit-test-station-codes",
                from_exp="origin-b",
            )

        self.assertEqual(check.await_count, 2)


if __name__ == "__main__":
    unittest.main()
