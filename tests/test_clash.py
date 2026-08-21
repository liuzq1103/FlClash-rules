import copy
import re
import unittest

import clash


def sample_config():
    proxies = [
        {"name": "🇺🇸 美国-01", "type": "ss", "server": "us.example", "port": 443},
        {"name": "🇭🇰 香港-01", "type": "ss", "server": "hk.example", "port": 443},
        {"name": "🇹🇼 台湾-01", "type": "ss", "server": "tw.example", "port": 443},
        {"name": "Expire: 2099-01-01", "type": "ss", "server": "info.example", "port": 443},
    ]
    names = [proxy["name"] for proxy in proxies]
    return {
        "proxies": proxies,
        "proxy-groups": [
            {"name": "手动选择", "type": "select", "proxies": ["自动选择"] + names},
            {"name": "Ai+", "type": "select", "proxies": ["手动选择"] + names},
            {"name": "漏网之鱼", "type": "select", "proxies": ["手动选择", "DIRECT"]},
            {"name": "自动选择", "type": "url-test", "proxies": names},
            {"name": "Google", "type": "select", "proxies": ["自动选择"]},
        ],
        "rule-providers": {
            "Apple": {
                "type": "http",
                "behavior": "classical",
                "path": "./providers/rule/AppleDev.yaml",
                "url": "https://example.test/Apple.yaml",
            },
            "AppleDev": {
                "type": "http",
                "behavior": "classical",
                "path": "./providers/rule/AppleDev.yaml",
                "url": "https://example.test/AppleDev.yaml",
            },
            "Google": {
                "type": "http",
                "behavior": "classical",
                "path": "./providers/rule/Google.yaml",
                "url": "https://example.test/Google.yaml",
            },
        },
        "rules": ["RULE-SET,Google,Google", "MATCH,漏网之鱼"],
    }


class RuleLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule_sets = clash.load_rule_sets()

    def test_expected_rule_sets_and_order(self):
        self.assertEqual(
            [rule_set["name"] for rule_set in self.rule_sets],
            [
                "Custom-Reject",
                "Custom-AI",
                "Custom-Academic",
                "Custom-Tailscale",
                "Custom-Direct",
            ],
        )

    def test_confirmed_omissions_are_filled(self):
        payload = {
            rule for rule_set in self.rule_sets for rule in rule_set["payload"]
        }
        expected = {
            "IP-CIDR6,fd7a:115c:a1e0::/48,no-resolve",
            "DOMAIN-SUFFIX,oup.com",
            "DOMAIN-SUFFIX,sciencedirectassets.com",
            "DOMAIN-SUFFIX,els-cdn.com",
            "DOMAIN-SUFFIX,githubcopilot.com",
            "DOMAIN-SUFFIX,hf.co",
            "DOMAIN-SUFFIX,claude.com",
            "DOMAIN-SUFFIX,x.ai",
        }
        self.assertTrue(expected.issubset(payload))

    def test_legacy_overbroad_rules_are_gone(self):
        payload = {
            rule for rule_set in self.rule_sets for rule in rule_set["payload"]
        }
        self.assertNotIn("DOMAIN-KEYWORD,google", payload)
        self.assertFalse(any(rule.startswith("IP-CIDR,216.239.0.0/16") for rule in payload))
        self.assertNotIn("DOMAIN-SUFFIX,example.com", payload)
        self.assertNotIn("DOMAIN-SUFFIX,oxfordjournals.org", payload)


class MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule_sets = clash.load_rule_sets()

    def test_groups_priorities_and_provider_path_fix(self):
        original = sample_config()
        original_auto = copy.deepcopy(clash._group_by_name(original, "自动选择"))
        merged = clash.apply_customizations(original, self.rule_sets)

        auto = clash._group_by_name(merged, "自动选择")
        self.assertEqual(auto, original_auto)

        ai_auto = clash._group_by_name(merged, "Ai自动选择")
        self.assertTrue(ai_auto["include-all-proxies"])
        self.assertIn("香港", ai_auto["exclude-filter"])
        self.assertEqual(ai_auto["exclude-type"], "direct")

        ai = clash._group_by_name(merged, "Ai+")
        self.assertEqual(ai["default-selected"], "Ai自动选择")
        self.assertEqual(ai["proxies"][0], "Ai自动选择")
        self.assertEqual(ai["exclude-type"], "direct")

        fallback = clash._group_by_name(merged, "漏网之鱼")
        self.assertEqual(fallback["proxies"][0], "DIRECT")
        self.assertEqual(fallback["default-selected"], "DIRECT")

        self.assertEqual(
            merged["rule-providers"]["Apple"]["path"],
            "./providers/rule/Apple.yaml",
        )

    def test_custom_rules_precede_subscription_rules(self):
        merged = clash.apply_customizations(sample_config(), self.rule_sets)
        expected = [
            f"RULE-SET,{rule_set['name']},{rule_set['target']}"
            for rule_set in self.rule_sets
        ]
        self.assertEqual(merged["rules"][: len(expected)], expected)
        self.assertEqual(merged["rules"][-1], "MATCH,漏网之鱼")

    def test_merge_is_idempotent(self):
        once = clash.apply_customizations(sample_config(), self.rule_sets)
        twice = clash.apply_customizations(once, self.rule_sets)
        self.assertEqual(once, twice)

    def test_ai_filter_matches_only_forbidden_or_informational_nodes(self):
        pattern = re.compile(clash.AI_EXCLUDE_FILTER)
        for name in ["🇭🇰 香港-01", "台湾家庭宽带", "Expire: 2099-01-01", "官网"]:
            self.assertRegex(name, pattern)
        for name in ["🇺🇸 美国-01", "🇩🇪 德国-01", "Shadowsocks-Moscow"]:
            self.assertNotRegex(name, pattern)


if __name__ == "__main__":
    unittest.main()
