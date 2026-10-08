"""Credential-free checks for the canonical API/worker configuration boundary."""

import re
import unittest
from pathlib import Path


class LLMOutputBudgetConfigurationTests(unittest.TestCase):
    def assert_service_budget(self, service: str) -> None:
        source = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
        match = re.search(r"(?ms)^  " + re.escape(service) + r":\n(.*?)(?=^  [a-z][\w-]*:\n|\Z)", source)
        self.assertIsNotNone(match)
        self.assertTrue(
            "- LLM_MAX_TOKENS=${LLM_MAX_TOKENS:-4096}" in match.group(1),
            f"Missing LLM_MAX_TOKENS forwarding for {service}",
        )

    def test_backend_receives_configurable_output_budget(self) -> None:
        self.assert_service_budget("backend")

    def test_worker_receives_the_same_configurable_output_budget(self) -> None:
        self.assert_service_budget("agent-worker")


if __name__ == "__main__":
    unittest.main()
