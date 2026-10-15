import copy
import re
import tempfile
import unittest
from pathlib import Path

import clash


US_NODES = [
    "🇺🇸 美国-01",
    "🇺🇸 美国-BGP-05【优化】",
    "🇺🇸 Basic-美国-BGP-01|v202605",
    "US-01",
]


def sample_config():
    proxies = [
        {"name": US_NODES[0], "type": "ss", "server": "us.example", "port": 443},
        {"name": US_NODES[1], "type": "ss", "server": "us-bgp.example", "port": 443},
        {"name": US_NODES[2], "type": "ss", "server": "us-basic.example", "port": 443},
        {"name": US_NODES[3], "type": "ss", "server": "us-ascii.example", "port": 443},
        {"name": "🇩🇪 德国-01", "type": "ss", "server": "de.example", "port": 443},
        {"name": "🇭🇰 香港-01", "type": "ss", "server": "hk.example", "port": 443},
        {"name": "🇹🇼 台湾-01", "type": "ss", "server": "tw.example", "port": 443},
        {"name": "Russia-Moscow-01", "type": "ss", "server": "ru.example", "port": 443},
        {"name": "Australia-Sydney-01", "type": "ss", "server": "au.example", "port": 443},
        {"name": "Expire: 2099-01-01", "type": "ss", "server": "info.example", "port": 443},
        {"name": "Traffic: 316.97GB | 1.66TB", "type": "ss", "server": "info2.example", "port": 443},
        {"name": "Sync: 2026-10-15 20:42:00", "type": "ss", "server": "info3.example", "port": 443},
        {"name": "🇺🇳 官网 helloshudong.com|v202605", "type": "ss", "server": "info4.example", "port": 443},
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
                "Custom-Scholar",
                "Custom-AI",
                "Custom-Academic",
                "Custom-Tailscale",
                "Custom-Direct",
            ],
        )

    def test_scholar_rules_precede_every_ai_rule(self):
        # Defensive ordering: mihomo is first-match, so the exact
        # scholar.google.com rules must come before ANY Ai+ rule (let alone a
        # hypothetical DOMAIN-SUFFIX,google.com) or they would be dead.
        expanded = clash._expand_custom_rules(self.rule_sets)
        scholar_indices = [
            index
            for index, rule in enumerate(expanded)
            if rule
            in ("DOMAIN,scholar.google.com,学术搜索", "DOMAIN,scholar.google.com.hk,学术搜索")
        ]
        self.assertEqual(len(scholar_indices), 2)
        first_ai = next(
            (index for index, rule in enumerate(expanded) if rule.endswith(",Ai+")),
            None,
        )
        self.assertIsNotNone(first_ai)
        self.assertLess(max(scholar_indices), first_ai)

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
            "DOMAIN-SUFFIX,claude.ai",
            "DOMAIN-SUFFIX,claude.com",
            "DOMAIN-SUFFIX,anthropic.com",
            "DOMAIN-SUFFIX,claudeusercontent.com",
            "DOMAIN-SUFFIX,x.ai",
            "DOMAIN,sea-ad-single-cell-profiling.s3.amazonaws.com",
        }
        self.assertTrue(expected.issubset(payload))

    def test_noise_rules_are_gone(self):
        payload = {
            rule for rule_set in self.rule_sets for rule in rule_set["payload"]
        }
        for gone in [
            "DOMAIN,default.exp-tas.com",
            "DOMAIN-SUFFIX,intercom.io",
            "DOMAIN-SUFFIX,roboflow.com",
            "DOMAIN-SUFFIX,generativelanguage.googleapis.com",
        ]:
            self.assertNotIn(gone, payload)

    def test_copilot_is_direct_not_ai(self):
        by_target = {
            rule_set["target"]: rule_set["payload"] for rule_set in self.rule_sets
        }
        self.assertIn("DOMAIN-SUFFIX,githubcopilot.com", by_target["DIRECT"])
        self.assertNotIn("DOMAIN-SUFFIX,githubcopilot.com", by_target["Ai+"])

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

    def test_gemini_shared_session_endpoints_keep_one_ai_exit(self):
        ai_payload = {
            rule
            for rule_set in self.rule_sets
            if rule_set["target"] == "Ai+"
            for rule in rule_set["payload"]
        }
        self.assertTrue(
            {
                "DOMAIN-SUFFIX,gemini.google.com",
                "DOMAIN,google.com",
                "DOMAIN,www.google.com",
                "DOMAIN,accounts.google.com",
                "DOMAIN,apis.google.com",
                "DOMAIN,ogs.google.com",
            }.issubset(ai_payload)
        )
        self.assertNotIn("DOMAIN-SUFFIX,google.com", ai_payload)

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
        self.assertEqual(ai_stable["proxies"], US_NODES)

        ai_auto = clash._group_by_name(merged, "Ai测速备用")
        self.assertEqual(ai_auto["proxies"], US_NODES)
        self.assertEqual(ai_auto["url"], clash.AI_PROBE_URL)
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

    def test_provider_subscription_uses_runtime_filter_without_raising(self):
        config = {
            "proxy-providers": {
                "sub": {"type": "http", "url": "https://example.test/sub"},
            },
            "proxy-groups": [
                {"name": "Ai+", "type": "select", "proxies": ["手动选择"]},
                {"name": "手动选择", "type": "select", "proxies": ["自动选择"]},
                {"name": "漏网之鱼", "type": "select", "proxies": ["手动选择", "DIRECT"]},
            ],
            "rule-providers": {},
            "rules": ["MATCH,漏网之鱼"],
        }
        merged = clash.apply_customizations(config, self.rule_sets)

        ai = clash._group_by_name(merged, "Ai+")
        self.assertEqual(ai["use"], ["sub"])
        self.assertEqual(ai["filter"], clash.AI_INCLUDE_FILTER)
        self.assertEqual(ai["exclude-filter"], clash.AI_EXCLUDE_FILTER)
        self.assertIsNone(clash._group_by_name(merged, "Ai稳定选择"))
        self.assertIsNone(clash._group_by_name(merged, "Ai测速备用"))
        self.assertEqual(
            clash._group_by_name(merged, "学术搜索")["proxies"], ["Ai+"]
        )
        self.assertEqual(
            clash._group_by_name(merged, "学术访问")["proxies"], ["DIRECT", "Ai+"]
        )
        expected = clash._expand_custom_rules(self.rule_sets)
        self.assertEqual(merged["rules"][: len(expected)], expected)

    def test_ai_filter_matches_us_whitelist_and_info_lines(self):
        include = re.compile(clash.AI_INCLUDE_FILTER)
        for name in [
            "🇺🇸 美国-01",
            "🇺🇸 美国-BGP-05【优化】",
            "🇺🇸 Basic-美国-BGP-01|v202605",
            "US-01",
            "USA-Los Angeles-02",
            "United States 03",
            "美國-傳統命名",
            # Whitelist wins over region words in the same name.
            "🇺🇸 美国优化-香港专线",
        ]:
            self.assertRegex(name, include)
        for name in [
            "🇩🇪 德国-01",
            "🇯🇵 日本-01",
            "🇸🇬 新加坡-01",
            "🇫🇮 芬兰-01",
            "Russia-Moscow-01",
            "Australia-Sydney-01",
        ]:
            self.assertNotRegex(name, include)

        exclude = re.compile(clash.AI_EXCLUDE_FILTER)
        for name in [
            "Expire: 2027-08-18",
            "Traffic: 316.97GB | 1.66TB",
            "Sync: 2026-10-15 20:42:00",
            "🇺🇳 官网 helloshudong.com|v202605",
            "剩余流量：1 TB",
            "套餐提示",
        ]:
            self.assertRegex(name, exclude)
        # Region filtering is AI_INCLUDE's job; AI_EXCLUDE must not touch it.
        for name in ["🇺🇸 美国-01", "US-01", "🇭🇰 香港-01", "🇩🇪 德国-01"]:
            self.assertNotRegex(name, exclude)


class ScriptGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule_sets = clash.load_rule_sets()

    def test_script_is_generated_without_subscription_or_secrets(self):
        script = clash.render_override_script(self.rule_sets)
        self.assertIn("function main(config)", script)
        self.assertIn('"DOMAIN,scholar.google.com,学术搜索"', script)
        self.assertIn('"DOMAIN,google.com,Ai+"', script)
        self.assertIn('"DOMAIN,accounts.google.com,Ai+"', script)
        self.assertNotIn('"DOMAIN-SUFFIX,google.com,Ai+"', script)
        self.assertIn('"DOMAIN-SUFFIX,science.org,学术访问"', script)
        self.assertNotIn("__CUSTOM_RULES_JSON__", script)
        self.assertNotIn("proxy-providers:", script)

    def test_atomic_text_writer_round_trips_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "override.js"
            clash.write_text_atomic(target, "const group = '学术搜索';\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "const group = '学术搜索';\n")

    def test_server_policy_is_secret_free_and_direct_by_default(self):
        policy = clash.build_server_policy(self.rule_sets)
        groups = {group["name"]: group for group in policy["proxy-groups"]}

        self.assertEqual(groups["Ai+"]["type"], "url-test")
        self.assertEqual(groups["Ai+"]["use"], ["subscription"])
        self.assertEqual(groups["Ai+"]["filter"], clash.AI_INCLUDE_FILTER)
        self.assertEqual(groups["Ai+"]["exclude-filter"], clash.AI_EXCLUDE_FILTER)
        self.assertEqual(groups["Ai+"]["url"], clash.AI_PROBE_URL)
        self.assertEqual(groups["学术搜索"]["proxies"], ["Ai+", "DIRECT"])
        self.assertEqual(groups["学术访问"]["proxies"], ["DIRECT", "Ai+"])
        self.assertEqual(policy["rules"][-1], "MATCH,DIRECT")
        self.assertIn(
            "DOMAIN,sea-ad-single-cell-profiling.s3.amazonaws.com,DIRECT",
            policy["rules"],
        )

        rendered = clash.render_server_policy(self.rule_sets)
        self.assertNotIn("proxy-providers:", rendered)
        self.assertNotRegex(
            rendered,
            r"(?i)(subscription[_-]?url|password|secret|token):",
        )


if __name__ == "__main__":
    unittest.main()
