"""Verify deployed seed calls cannot omit or misroute the portal product key."""

import unittest
from unittest.mock import patch

from scripts.seed import SeedSettings, main


class SeedSubscriptionTests(unittest.TestCase):
    def settings(self, url: str, key: str = "") -> SeedSettings:
        return SeedSettings(
            _env_file=None,
            seed_api_url=url,
            seed_access_token="test-admin-token",
            seed_apim_subscription_key=key,
            seed_local_auth=False,
        )

    def test_portal_requires_product_key_before_network(self) -> None:
        with (
            patch("sys.argv", ["seed.py", "--apply"]),
            patch(
                "scripts.seed.SeedSettings", return_value=self.settings("https://gateway/portal")
            ),
            patch("scripts.seed.httpx.Client") as client,
        ):
            with self.assertRaisesRegex(ValueError, "SEED_APIM_SUBSCRIPTION_KEY"):
                main()
            client.assert_not_called()

    def test_portal_forwards_both_credentials_in_headers(self) -> None:
        with (
            patch("sys.argv", ["seed.py", "--apply"]),
            patch(
                "scripts.seed.SeedSettings",
                return_value=self.settings("https://gateway/portal", "test-portal-key"),
            ),
            patch("scripts.seed.httpx.Client") as client,
            patch("builtins.print") as output,
        ):
            main()
            headers = client.call_args.kwargs["headers"]
            self.assertEqual(headers["Authorization"], "Bearer test-admin-token")
            self.assertEqual(headers["Ocp-Apim-Subscription-Key"], "test-portal-key")
            for call in client.return_value.__enter__.return_value.put.call_args_list:
                self.assertNotIn("test-portal-key", call.args[0])
            self.assertNotIn("test-portal-key", str(output.call_args_list))

    def test_key_cannot_be_forwarded_to_a_direct_function(self) -> None:
        with (
            patch("sys.argv", ["seed.py", "--apply"]),
            patch(
                "scripts.seed.SeedSettings",
                return_value=self.settings("https://function/api", "test-portal-key"),
            ),
            patch("scripts.seed.httpx.Client") as client,
        ):
            with self.assertRaisesRegex(ValueError, "APIM /portal"):
                main()
            client.assert_not_called()
