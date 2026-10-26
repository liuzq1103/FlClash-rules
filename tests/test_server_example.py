"""Offline deployment contract: concatenate the two published fragments."""
import unittest
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml

import clash


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "server-provider.example.yaml"


class ServerExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider_text = EXAMPLE.read_text(encoding="utf-8")
        cls.policy_text = (ROOT / "dist/server-policy.yaml").read_text(encoding="utf-8")
        cls.combined = yaml.safe_load(cls.provider_text + cls.policy_text)

    def test_concatenation_is_one_complete_routing_document(self):
        self.assertTrue(self.provider_text.endswith("\n"))
        documents = list(yaml.safe_load_all(self.provider_text + self.policy_text))
        self.assertEqual(len(documents), 1)
        self.assertEqual(set(self.combined), {"proxy-providers", "proxy-groups", "rules"})
        self.assertEqual(
            {k: self.combined[k] for k in ("proxy-groups", "rules")},
            clash.build_server_policy(clash.load_rule_sets()),
        )

    def test_all_provider_members_and_rule_targets_resolve(self):
        groups = {g["name"]: g for g in self.combined["proxy-groups"]}
        self.assertEqual(len(groups), len(self.combined["proxy-groups"]))
        providers = self.combined["proxy-providers"]
        direct = {name for name, g in groups.items() if g.get("use")}
        self.assertEqual(direct, {"PROXY", "Ai稳定选择", "Ai测速备用", "Dev+"})
        targets = set(groups) | clash.BUILTIN_TARGETS
        for name, group in groups.items():
            with self.subTest(group=name):
                self.assertTrue(set(group.get("use", [])) <= set(providers))
                self.assertTrue(set(group.get("proxies", [])) <= targets)
        for rule in self.combined["rules"]:
            self.assertIn(clash._rule_target(rule), targets, rule)
        self.assertEqual(self.combined["rules"][-1], "MATCH,DIRECT")

    def test_provider_cache_path_and_placeholder_are_safe(self):
        providers = self.combined["proxy-providers"]
        self.assertEqual(set(providers), {"subscription"})
        used = set()
        for provider in providers.values():
            self.assertEqual(provider["type"], "http")
            url = urlsplit(provider["url"])
            self.assertEqual(url.scheme, "https")
            self.assertEqual(url.hostname, "subscription.example.invalid")
            self.assertEqual(url.path, "/REPLACE_WITH_PRIVATE_SUBSCRIPTION")
            self.assertIsNone(url.username)
            self.assertIsNone(url.password)
            self.assertFalse(url.query or url.fragment)
            path = PurePosixPath(provider["path"])
            self.assertEqual(str(path), "proxy_providers/subscription.yaml")
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)
            self.assertNotIn(path, used)
            used.add(path)
            self.assertEqual(provider["health-check"]["url"], clash.GENERIC_PROBE_URL)

    def test_policy_format_and_filter_values_survive_composition(self):
        self.assertIn("proxy-groups:\n- name:", self.policy_text)
        self.assertIn("\n  use:\n  - subscription\n", self.policy_text)
        self.assertNotIn("__flclashRules", self.combined)
        groups = {g["name"]: g for g in self.combined["proxy-groups"]}
        for name in ("Ai稳定选择", "Ai测速备用"):
            self.assertEqual(groups[name]["filter"], clash.AI_INCLUDE_FILTER)
        self.assertEqual(groups["Dev+"]["filter"], clash.DEV_INCLUDE_FILTER)
        for name in ("PROXY", "Ai稳定选择", "Ai测速备用", "Dev+"):
            self.assertEqual(groups[name]["exclude-filter"], clash.AI_EXCLUDE_FILTER)
        # Every regex occupies one physical YAML line, preventing folded spaces.
        filter_lines = [line for line in self.policy_text.splitlines()
                        if line.lstrip().startswith(("filter:", "exclude-filter:"))]
        self.assertEqual(len(filter_lines), 7)

    def test_example_has_no_nodes_or_host_runtime_credentials(self):
        forbidden = {"proxies", "listeners", "authentication", "secret", "password",
                     "token", "uuid", "external-controller", "mixed-port", "tun"}

        def walk(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        # Group 'proxies' are names, not node credentials; inspect the provider
        # fragment recursively and constrain the policy's root separately.
        walk(yaml.safe_load(self.provider_text))
        self.assertEqual(set(yaml.safe_load(self.policy_text)), {"proxy-groups", "rules"})


if __name__ == "__main__":
    unittest.main()
