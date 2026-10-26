import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import index
from config import MAX_CONCURRENT_CHECKS


class BackgroundCheckerLoadTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_subscription_set_uses_bounded_workers(self):
        subscriptions = [
            (str(user_id), {"id": f"subscription-{user_id}"})
            for user_id in range(1000)
        ]
        processed = []
        active_checks = 0
        peak_active_checks = 0

        async def simulated_check(
            context, user_id, sub, is_first_check=False
        ):
            nonlocal active_checks, peak_active_checks
            self.assertIsNotNone(context)
            self.assertGreaterEqual(user_id, 0)
            self.assertFalse(is_first_check)
            active_checks += 1
            peak_active_checks = max(peak_active_checks, active_checks)
            await asyncio.sleep(0)
            processed.append(sub["id"])
            active_checks -= 1

        with (
            patch.object(index, "cleanup_expired"),
            patch.object(index, "active_subscriptions", return_value=subscriptions),
            patch.object(index, "check_single_subscription", new=simulated_check),
        ):
            await index.background_checker(SimpleNamespace())

        self.assertEqual(len(processed), len(subscriptions))
        self.assertEqual(len(set(processed)), len(subscriptions))
        self.assertLessEqual(peak_active_checks, MAX_CONCURRENT_CHECKS)
        self.assertEqual(peak_active_checks, min(MAX_CONCURRENT_CHECKS, len(subscriptions)))

    async def test_failed_subscription_does_not_stop_remaining_checks(self):
        subscriptions = [
            (str(user_id), {"id": f"subscription-{user_id}"})
            for user_id in range(5)
        ]
        processed = []

        async def simulated_check(
            context, user_id, sub, is_first_check=False
        ):
            self.assertIsNotNone(context)
            self.assertGreaterEqual(user_id, 0)
            self.assertFalse(is_first_check)
            if sub["id"] == "subscription-2":
                raise RuntimeError("simulated check failure")
            processed.append(sub["id"])

        with (
            patch.object(index, "cleanup_expired"),
            patch.object(index, "active_subscriptions", return_value=subscriptions),
            patch.object(index, "check_single_subscription", new=simulated_check),
            self.assertLogs(level="ERROR") as captured,
        ):
            await index.background_checker(SimpleNamespace())

        self.assertEqual(len(processed), 4)
        self.assertTrue(
            any("subscription-2" in message for message in captured.output)
        )


if __name__ == "__main__":
    unittest.main()
