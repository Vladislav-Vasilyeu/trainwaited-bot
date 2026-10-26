import json
import os
import tempfile
import unittest

import storage


class SubscriptionStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.SUBSCRIPTIONS_FILE
        self.original_subscriptions = storage.subscriptions
        storage.SUBSCRIPTIONS_FILE = os.path.join(self.temp_dir.name, "data", "subscriptions.json")
        storage.subscriptions = {}

    def tearDown(self):
        storage.SUBSCRIPTIONS_FILE = self.original_path
        storage.subscriptions = self.original_subscriptions
        self.temp_dir.cleanup()

    def test_save_and_load_round_trip(self):
        storage.subscriptions = {"123": [{"id": "abc", "date": "2099-01-01"}]}
        storage.save_subscriptions()
        storage.subscriptions = {}

        storage.load_subscriptions()

        self.assertEqual(storage.subscriptions["123"][0]["id"], "abc")
        self.assertEqual(
            os.listdir(os.path.dirname(storage.SUBSCRIPTIONS_FILE)),
            ["subscriptions.json"],
        )

    def test_invalid_json_is_not_replaced_with_empty_data(self):
        os.makedirs(os.path.dirname(storage.SUBSCRIPTIONS_FILE))
        with open(storage.SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as file:
            file.write("{")

        with self.assertLogs(level="ERROR"):
            with self.assertRaises(json.JSONDecodeError):
                storage.load_subscriptions()

        self.assertEqual(storage.subscriptions, {})

    def test_station_codes_and_display_labels_are_saved_with_subscription(self):
        sub = storage.create_subscription(
            "123",
            "unit-test-train",
            "2099-01-01",
            "Москва Белорусская",
            "Брест-Центральный",
            from_exp="2000006",
            to_exp="2100001",
            from_label="ст. Москва Белорусская, Россия",
            to_label="ст. Брест-Центральный",
        )

        self.assertEqual(sub["from_exp"], "2000006")
        self.assertEqual(sub["to_exp"], "2100001")
        self.assertEqual(sub["from_label"], "ст. Москва Белорусская, Россия")
        self.assertEqual(sub["to_label"], "ст. Брест-Центральный")


if __name__ == "__main__":
    unittest.main()
