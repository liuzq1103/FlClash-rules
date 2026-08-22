import copy
import re
import tempfile
import unittest
from pathlib import Path

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
        "rules": [
            "DOMAIN-SUFFIX,science.org,DIRECT",
            "RULE-SET,Custom-Academic,DIRECT",
            "RULE-SET,Google,Google",
            "MATCH,漏网之鱼",
        ],
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
                "Custom-Scholar",
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

    def test_scholar_uses_narrow_exact_domains(self):
        scholar = next(
            rule_set for rule_set in self.rule_sets if rule_set["name"] == "Custom-Scholar"
        )
        self.assertEqual(scholar["target"], "学术搜索")
        self.assertEqual(
            scholar["payload"],
            ["DOMAIN,scholar.google.com", "DOMAIN,scholar.google.com.hk"],
        )

    def test_academic_sites_use_direct_first_switchable_route(self):
        by_target = {
            target: {
                rule
                for rule_set in self.rule_sets
                if rule_set["target"] == target
                for rule in rule_set["payload"]
            }
            for target in {rule_set["target"] for rule_set in self.rule_sets}
        }
        switchable = {
            "DOMAIN-SUFFIX,science.org",
            "DOMAIN-SUFFIX,pnas.org",
            "DOMAIN-SUFFIX,oup.com",
            "DOMAIN-SUFFIX,tandfonline.com",
            "DOMAIN-SUFFIX,cell.com",
        }
        self.assertTrue(switchable.issubset(by_target["学术访问"]))
        self.assertTrue(switchable.isdisjoint(by_target["Ai+"]))
        self.assertIn("DOMAIN-SUFFIX,challenges.cloudflare.com", by_target["Ai+"])

    def test_chatgpt_core_is_owned_by_custom_ai_rules(self):
        ai_payload = {
            rule
            for rule_set in self.rule_sets
            if rule_set["target"] == "Ai+"
            for rule in rule_set["payload"]
        }
        self.assertTrue(
            {
                "DOMAIN-SUFFIX,chatgpt.com",
                "DOMAIN-SUFFIX,openai.com",
                "DOMAIN-SUFFIX,oaistatic.com",
                "DOMAIN-SUFFIX,oaiusercontent.com",
            }.issubset(ai_payload)
        )

    def test_route_constraint_rejects_cross_exit_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "site.yaml").write_text(
                "payload:\n  - DOMAIN-SUFFIX,science.org\n", encoding="utf-8"
            )
            index = root / "index.yml"
            index.write_text(
                "rule-sets:\n"
                "  - name: Custom-Site\n"
                "    file: site.yaml\n"
                "    target: 学术访问\n"
                "route-constraints:\n"
                "  - name: affinity\n"
                "    target: Ai+\n"
                "    rules:\n"
                "      - DOMAIN-SUFFIX,science.org\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(clash.ConfigError, "requires.*Ai.*found 学术访问"):
                clash.load_rule_sets(index)


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

        ai_stable = clash._group_by_name(merged, "Ai稳定选择")
        self.assertEqual(ai_stable["proxies"], ["🇺🇸 美国-01"])

        ai_auto = clash._group_by_name(merged, "Ai测速备用")
        self.assertEqual(ai_auto["proxies"], ["🇺🇸 美国-01"])
        self.assertEqual(ai_auto["url"], "https://chatgpt.com/cdn-cgi/trace")
        self.assertEqual(ai_auto["expected-status"], 200)
        self.assertNotIn("include-all-proxies", ai_auto)
        self.assertNotIn("exclude-filter", ai_auto)

        ai = clash._group_by_name(merged, "Ai+")
        self.assertEqual(ai["proxies"], ["Ai稳定选择", "Ai测速备用"])
        self.assertNotIn("include-all-proxies", ai)
        self.assertNotIn("default-selected", ai)

        scholar = clash._group_by_name(merged, "学术搜索")
        self.assertEqual(scholar["proxies"], ["Ai稳定选择", "Ai测速备用"])

        academic = clash._group_by_name(merged, "学术访问")
        self.assertEqual(academic["proxies"], ["DIRECT", "Ai+"])

        fallback = clash._group_by_name(merged, "漏网之鱼")
        self.assertEqual(fallback["proxies"][0], "DIRECT")
        self.assertNotIn("default-selected", fallback)

        self.assertEqual(
            merged["rule-providers"]["Apple"]["path"],
            "./providers/rule/Apple.yaml",
        )

    def test_custom_rules_precede_subscription_rules(self):
        merged = clash.apply_customizations(sample_config(), self.rule_sets)
        expected = clash._expand_custom_rules(self.rule_sets)
        self.assertEqual(merged["rules"][: len(expected)], expected)
        self.assertEqual(merged["rules"][-1], "MATCH,漏网之鱼")
        self.assertNotIn("DOMAIN-SUFFIX,science.org,DIRECT", merged["rules"])
        self.assertIn("DOMAIN-SUFFIX,science.org,学术访问", merged["rules"])
        self.assertNotIn("DOMAIN-SUFFIX,science.org,Ai+", merged["rules"])
        self.assertNotIn("RULE-SET,Custom-Academic,DIRECT", merged["rules"])
        self.assertFalse(
            any(name.startswith("Custom-") for name in merged["rule-providers"])
        )

    def test_merge_is_idempotent(self):
        once = clash.apply_customizations(sample_config(), self.rule_sets)
        twice = clash.apply_customizations(once, self.rule_sets)
        self.assertEqual(once, twice)

    def test_ai_filter_matches_only_forbidden_or_informational_nodes(self):
        pattern = re.compile(clash.AI_EXCLUDE_FILTER)
        for name in [
            "🇭🇰 香港-01",
            "台湾家庭宽带",
            "Expire: 2099-01-01",
            "剩余流量：1 TB",
            "官网",
        ]:
            self.assertRegex(name, pattern)
        for name in ["🇺🇸 美国-01", "🇩🇪 德国-01", "Shadowsocks-Moscow"]:
            self.assertNotRegex(name, pattern)


class ScriptGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule_sets = clash.load_rule_sets()

    def test_script_is_generated_without_subscription_or_secrets(self):
        script = clash.render_override_script(self.rule_sets)
        self.assertIn("function main(config)", script)
        self.assertIn('"DOMAIN,scholar.google.com,学术搜索"', script)
        self.assertIn('"DOMAIN-SUFFIX,science.org,学术访问"', script)
        self.assertNotIn("__CUSTOM_RULES_JSON__", script)
        self.assertNotIn("proxy-providers:", script)

    def test_atomic_text_writer_round_trips_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "override.js"
            clash.write_text_atomic(target, "const group = '学术搜索';\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "const group = '学术搜索';\n")


if __name__ == "__main__":
    unittest.main()
