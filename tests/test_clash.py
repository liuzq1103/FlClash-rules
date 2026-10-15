import copy
import re
import tempfile
import unittest
from pathlib import Path

import yaml

import clash


US_NODES = [
    "🇺🇸 美国-01",
    "🇺🇸 美国-BGP-05【优化】",
    "🇺🇸 Basic-美国-BGP-01|v202605",
    "US-01",
]

# A second airport with food-themed names, "| protocol" suffixes and four
# different info lines. It has no Ai+ group at all.
NANO_US_NODES = [
    "🇺🇸 狮城沙嗲串 | IPv4",
    "🇺🇸 美国龙虾卷 | DDNSv4",
    "🇺🇸 美国奶油派 | CT IP",
]
NANO_OTHER_NODES = ["🇸🇬 狮城肉骨茶 | IPv4", "🇯🇵 日本天妇罗 | DDNSv4", "🇭🇰 香港碳仔雞 | IPv4"]
NANO_INFO_NODES = [
    "剩余流量: 876.18 GB",
    "距离下次重置剩余：24 天",
    "套餐到期：2027-10-08",
    # Airport hostnames are anonymised: the filter only needs the shape.
    "官网 example.invalid example2.invalid 群组 t.me/example",
]


def sample_config():
    proxies = [
        {"name": US_NODES[0], "type": "ss", "server": "us.example", "port": 443},
        {"name": US_NODES[1], "type": "ss", "server": "us-bgp.example", "port": 443},
        {"name": US_NODES[2], "type": "ss", "server": "us-basic.example", "port": 443},
        {"name": US_NODES[3], "type": "ss", "server": "us-ascii.example", "port": 443},
        {"name": "🇩🇪 德国-01", "type": "ss", "server": "de.example", "port": 443},
        {"name": "🇭🇰 香港-01", "type": "ss", "server": "hk.example", "port": 443},
        {"name": "Russia-Moscow-01", "type": "ss", "server": "ru.example", "port": 443},
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


def nanoport_config():
    names = NANO_US_NODES + NANO_OTHER_NODES + NANO_INFO_NODES
    return {
        "proxies": [
            {"name": name, "type": "vless", "server": f"n{i}.example", "port": 443}
            for i, name in enumerate(names)
        ],
        "proxy-groups": [
            {"name": "自动选择", "type": "url-test", "proxies": names},
            {"name": "战略转移", "type": "url-test", "proxies": names},
            {"name": "漏网之鱼", "type": "select", "proxies": ["自动选择", "DIRECT"]},
        ],
        "rule-providers": {},
        "rules": ["DOMAIN-SUFFIX,bilibili.com,DIRECT", "MATCH,漏网之鱼"],
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
                "Custom-Priority",
                "Custom-Scholar",
                "Custom-AI",
                "Custom-Dev",
                "Custom-Academic",
                "Custom-Tailscale",
                "Custom-Direct",
            ],
        )

    def test_desktop_only_rule_sets(self):
        by_name = {rule_set["name"]: rule_set for rule_set in self.rule_sets}
        for client_only in ("Custom-Reject", "Custom-Tailscale", "Custom-Direct"):
            self.assertEqual(by_name[client_only]["artifacts"], ["client"])
        for shared in ("Custom-Priority", "Custom-Scholar", "Custom-AI", "Custom-Dev"):
            self.assertEqual(
                sorted(by_name[shared]["artifacts"]), ["client", "server"]
            )

    def test_scholar_rules_precede_every_ai_rule(self):
        # Defensive ordering: mihomo is first-match, so the exact
        # scholar.google.com rules must come before ANY Ai+ rule (let alone
        # DOMAIN-SUFFIX,google.com) or they would be dead rules.
        expanded = clash._expand_custom_rules(self.rule_sets, clash.ARTIFACT_CLIENT)
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

    def test_google_is_one_suffix_rule(self):
        ai_payload = {
            rule
            for rule_set in self.rule_sets
            if rule_set["target"] == "Ai+"
            for rule in rule_set["payload"]
        }
        self.assertIn("DOMAIN-SUFFIX,google.com", ai_payload)
        # The old per-endpoint exact rules are covered by the suffix now.
        for redundant in (
            "DOMAIN,www.google.com",
            "DOMAIN,accounts.google.com",
            "DOMAIN,ogs.google.com",
            "DOMAIN-SUFFIX,gemini.google.com",
            "DOMAIN-SUFFIX,aistudio.google.com",
        ):
            self.assertNotIn(redundant, ai_payload)

    def test_confirmed_omissions_are_filled(self):
        payload = {
            rule for rule_set in self.rule_sets for rule in rule_set["payload"]
        }
        expected = {
            "IP-CIDR6,fd7a:115c:a1e0::/48,no-resolve",
            "DOMAIN-SUFFIX,oup.com",
            "DOMAIN-SUFFIX,sciencedirectassets.com",
            "DOMAIN-SUFFIX,els-cdn.com",
            "DOMAIN-SUFFIX,hf.co",
            "DOMAIN-SUFFIX,claude.ai",
            "DOMAIN-SUFFIX,claude.com",
            "DOMAIN-SUFFIX,anthropic.com",
            "DOMAIN-SUFFIX,claudeusercontent.com",
            "DOMAIN-SUFFIX,x.ai",
            "DOMAIN-SUFFIX,openai.fm",
            "DOMAIN-SUFFIX,sora.com",
            "DOMAIN-SUFFIX,perplexity.ai",
            "DOMAIN-SUFFIX,poe.com",
            "DOMAIN-SUFFIX,ggpht.com",
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
            "DOMAIN-SUFFIX,production.cloudflare.docker.com",
            "DOMAIN-SUFFIX,registry-1.docker.io",
        ]:
            self.assertNotIn(gone, payload)

    def test_development_traffic_lives_in_dev_rule_set(self):
        by_name = {rule_set["name"]: rule_set for rule_set in self.rule_sets}
        dev = by_name["Custom-Dev"]
        self.assertEqual(dev["target"], "Ai+")
        self.assertEqual(dev["server-target"], "Dev+")
        for rule in [
            "DOMAIN-SUFFIX,github.com",
            "DOMAIN-SUFFIX,githubcopilot.com",
            "DOMAIN-SUFFIX,github.io",
            "DOMAIN-SUFFIX,sourcegraph.com",
            "DOMAIN-SUFFIX,huggingface.co",
            "DOMAIN-SUFFIX,docker.io",
            "DOMAIN-SUFFIX,cursor.sh",
        ]:
            self.assertIn(rule, dev["payload"])
        # No longer scattered across other rule-sets.
        everywhere = {
            rule for rule_set in self.rule_sets for rule in rule_set["payload"]
        }
        self.assertEqual(
            [rule for rule in everywhere if rule == "DOMAIN-SUFFIX,github.com"],
            ["DOMAIN-SUFFIX,github.com"],
        )

    def test_priority_direct_rules_come_first(self):
        expanded = clash._expand_custom_rules(self.rule_sets, clash.ARTIFACT_SERVER)
        self.assertEqual(
            expanded[:2],
            [
                "DOMAIN,sea-ad-single-cell-profiling.s3.amazonaws.com,DIRECT",
                "DOMAIN-SUFFIX,ncbi.nlm.nih.gov,DIRECT",
            ],
        )
        # ncbi moved from Ai+ to DIRECT.
        self.assertNotIn("DOMAIN-SUFFIX,ncbi.nlm.nih.gov,Ai+", expanded)

    def test_artifacts_expand_to_their_own_targets(self):
        client = clash._expand_custom_rules(self.rule_sets, clash.ARTIFACT_CLIENT)
        server = clash._expand_custom_rules(self.rule_sets, clash.ARTIFACT_SERVER)
        self.assertIn("DOMAIN-SUFFIX,github.com,Ai+", client)
        self.assertIn("DOMAIN-SUFFIX,github.com,Dev+", server)
        self.assertNotIn("DOMAIN-SUFFIX,github.com,Dev+", client)
        self.assertNotIn("DOMAIN-SUFFIX,githubcopilot.com,DIRECT", client)
        # Desktop-only rule-sets never reach the server artifact.
        for rule in ("DOMAIN-SUFFIX,adobedtm.com", "DOMAIN-SUFFIX,bing.com"):
            self.assertIn(f"{rule},DIRECT", client)
            self.assertNotIn(f"{rule},DIRECT", server)
        self.assertIn("DOMAIN-SUFFIX,doubleclick.net,REJECT", client)
        self.assertNotIn("DOMAIN-SUFFIX,doubleclick.net,REJECT", server)
        self.assertIn("DOMAIN-SUFFIX,tailscale.io,DIRECT", client)
        self.assertNotIn("DOMAIN-SUFFIX,tailscale.io,DIRECT", server)

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

    def test_invalid_artifact_and_server_target_are_rejected(self):
        cases = [
            ("artifacts: [desktop]", "artifacts"),
            ("artifacts: [client, client]", "repeats an artifact"),
            # A server-target that can never apply is a silent typo trap.
            (
                "artifacts: [client]\n    server-target: Dev+",
                "not part of the server artifact",
            ),
        ]
        for extra, message in cases:
            with self.subTest(extra=extra):
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
                        "    target: Ai+\n"
                        f"    {extra}\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(clash.ConfigError, message):
                        clash.load_rule_sets(index)

    def test_shadow_validation_respects_artifact_membership(self):
        # The broader rule lives in a desktop-only rule-set and the narrower one
        # in a server-only rule-set, so neither artifact contains a shadow even
        # though both resolve to the same target.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broad.yaml").write_text(
                "payload:\n  - DOMAIN-SUFFIX,nih.gov\n", encoding="utf-8"
            )
            (root / "narrow.yaml").write_text(
                "payload:\n  - DOMAIN-SUFFIX,ncbi.nlm.nih.gov\n", encoding="utf-8"
            )
            index = root / "index.yml"
            index.write_text(
                "rule-sets:\n"
                "  - name: Custom-Broad\n"
                "    file: broad.yaml\n"
                "    target: REJECT\n"
                "    artifacts: [client]\n"
                "  - name: Custom-Narrow\n"
                "    file: narrow.yaml\n"
                "    target: REJECT\n"
                "    artifacts: [server]\n",
                encoding="utf-8",
            )
            rule_sets = clash.load_rule_sets(index)
            self.assertEqual(
                clash._expand_custom_rules(rule_sets, clash.ARTIFACT_CLIENT),
                ["DOMAIN-SUFFIX,nih.gov,REJECT"],
            )
            self.assertEqual(
                clash._expand_custom_rules(rule_sets, clash.ARTIFACT_SERVER),
                ["DOMAIN-SUFFIX,ncbi.nlm.nih.gov,REJECT"],
            )

    def test_shadow_validation_still_catches_real_same_artifact_shadow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broad.yaml").write_text(
                "payload:\n  - DOMAIN-SUFFIX,nih.gov\n", encoding="utf-8"
            )
            (root / "narrow.yaml").write_text(
                "payload:\n  - DOMAIN-SUFFIX,ncbi.nlm.nih.gov\n", encoding="utf-8"
            )
            index = root / "index.yml"
            index.write_text(
                "rule-sets:\n"
                "  - name: Custom-Broad\n"
                "    file: broad.yaml\n"
                "    target: REJECT\n"
                "  - name: Custom-Narrow\n"
                "    file: narrow.yaml\n"
                "    target: REJECT\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(clash.ConfigError, "redundant rule"):
                clash.load_rule_sets(index)


class NodeFilterTests(unittest.TestCase):
    def test_include_matches_us_naming_styles(self):
        pattern = re.compile(clash.AI_INCLUDE_FILTER)
        for name in US_NODES + NANO_US_NODES + [
            "USA-Los Angeles-02",
            "United States 03",
            "America-Los Angeles 05",
            "U.S.A 01",
            "美國-傳統命名",
            "🇺🇸 美国优化-香港专线",
        ]:
            self.assertRegex(name, pattern)
        for name in NANO_OTHER_NODES + [
            "🇩🇪 德国-01",
            "🇯🇵 日本-01",
            "🇸🇬 新加坡-01",
            "Russia-Moscow-01",
            "Australia-Sydney-01",
        ]:
            self.assertNotRegex(name, pattern)

    def test_dev_include_adds_hong_kong(self):
        dev = re.compile(clash.DEV_INCLUDE_FILTER)
        for name in [
            "🇭🇰 香港碳仔雞 | IPv4",
            "香港 01",
            "HK-02",
            "HKG-IEPL-03",  # IATA spelling: a letter follows "hk"
            "US-01",
            "🇺🇸 美国龙虾卷",
        ]:
            self.assertRegex(name, dev)
        for name in ["🇯🇵 日本天妇罗", "Russia-Moscow-01", "剩余流量: 876.18 GB"]:
            self.assertNotRegex(name, dev)

    def test_exclude_strips_airport_info_lines(self):
        pattern = re.compile(clash.AI_EXCLUDE_FILTER)
        for name in [
            "Expire: 2027-08-18",
            "Traffic: 316.97GB | 1.66TB",
            "Sync: 2026-10-15 20:42:00",
            "🇺🇳 官网 example.invalid|v202605",
            "剩余流量: 876.18 GB",
            "距离下次重置剩余：24 天",
            "套餐到期：2027-10-08",
            "官网 example.invalid 群组 t.me/example",
            "【官网】example.invalid",
            "Expire20270818",
            "Traffic20270818GB",
            "过期时间：2027-08-18",
            "到期 2027-10-08",
            "剩余：100GB",
        ]:
            self.assertRegex(name, pattern)
        # Region filtering is AI_INCLUDE's job; real nodes stay.
        for name in US_NODES + NANO_US_NODES + NANO_OTHER_NODES:
            self.assertNotRegex(name, pattern)
        # Marketing-style names that merely contain 到期/过期 are real nodes and
        # must stay selectable.
        for name in [
            "🇭🇰 香港 永不过期 01",
            "🇯🇵 日本 到期专线 01",
            "🇺🇸 美国 重置专线 02",
        ]:
            self.assertNotRegex(name, pattern)


class MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule_sets = clash.load_rule_sets()

    def test_inline_groups_and_provider_path_fix(self):
        original = sample_config()
        original_auto = copy.deepcopy(clash._group_by_name(original, "自动选择"))
        merged = clash.apply_customizations(original, self.rule_sets)

        self.assertEqual(clash._group_by_name(merged, "自动选择"), original_auto)

        ai_stable = clash._group_by_name(merged, "Ai稳定选择")
        self.assertEqual(ai_stable["proxies"], US_NODES)

        ai_auto = clash._group_by_name(merged, "Ai测速备用")
        self.assertEqual(ai_auto["proxies"], US_NODES)
        self.assertEqual(ai_auto["url"], clash.AI_PROBE_URL)
        self.assertEqual(ai_auto["expected-status"], 200)
        self.assertNotIn("use", ai_auto)

        ai = clash._group_by_name(merged, "Ai+")
        self.assertEqual(ai["type"], "select")
        self.assertEqual(ai["proxies"], ["Ai稳定选择", "Ai测速备用"])
        self.assertNotIn("filter", ai)

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
        expected = clash._expand_custom_rules(self.rule_sets, clash.ARTIFACT_CLIENT)
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

    def test_provider_subscription_gets_the_same_group_shape(self):
        config = {
            "proxy-providers": {"sub": {"type": "http", "url": "https://example.test/sub"}},
            "proxy-groups": [
                {"name": "自动选择", "type": "url-test", "use": ["sub"]},
                {"name": "Ai+", "type": "url-test", "proxies": []},
                {"name": "漏网之鱼", "type": "select", "proxies": ["自动选择", "DIRECT"]},
            ],
            "rule-providers": {},
            "rules": ["MATCH,漏网之鱼"],
        }
        merged = clash.apply_customizations(config, self.rule_sets)

        stable = clash._group_by_name(merged, "Ai稳定选择")
        auto = clash._group_by_name(merged, "Ai测速备用")
        for group in (stable, auto):
            self.assertEqual(group["use"], ["sub"])
            self.assertEqual(group["filter"], clash.AI_INCLUDE_FILTER)
            self.assertEqual(group["exclude-filter"], clash.AI_EXCLUDE_FILTER)
            self.assertNotIn("proxies", group)
        self.assertEqual(auto["url"], clash.AI_PROBE_URL)
        self.assertEqual(
            clash._group_by_name(merged, "Ai+")["proxies"],
            ["Ai稳定选择", "Ai测速备用"],
        )
        self.assertEqual(
            clash._group_by_name(merged, "学术搜索")["proxies"],
            ["Ai稳定选择", "Ai测速备用"],
        )
        # A url-test Ai+ from the subscription is coerced to select.
        self.assertEqual(clash._group_by_name(merged, "Ai+")["type"], "select")

    def test_missing_ai_group_is_created(self):
        merged = clash.apply_customizations(nanoport_config(), self.rule_sets)

        names = [group["name"] for group in merged["proxy-groups"]]
        self.assertIn("Ai+", names)
        self.assertLess(names.index("Ai+"), names.index("漏网之鱼"))
        self.assertEqual(
            clash._group_by_name(merged, "Ai稳定选择")["proxies"], NANO_US_NODES
        )
        for name in NANO_OTHER_NODES + NANO_INFO_NODES:
            self.assertNotIn(name, clash._group_by_name(merged, "Ai稳定选择")["proxies"])
        # Untouched groups of the new airport survive.
        self.assertTrue(clash._group_by_name(merged, "战略转移"))
        self.assertIn("DOMAIN-SUFFIX,bilibili.com,DIRECT", merged["rules"])

    def test_rules_for_absent_targets_are_skipped(self):
        config = {
            "proxies": [{"name": "🇯🇵 日本-01", "type": "ss", "server": "jp", "port": 443}],
            "proxy-groups": [
                {"name": "自动选择", "type": "url-test", "proxies": ["🇯🇵 日本-01"]},
                {"name": "漏网之鱼", "type": "select", "proxies": ["自动选择", "DIRECT"]},
            ],
            "rule-providers": {},
            "rules": ["MATCH,漏网之鱼"],
        }
        # No US node and no provider: no AI groups, and no rule may point at a
        # target this config does not define.
        merged = clash.apply_customizations(config, self.rule_sets)

        self.assertIsNone(clash._group_by_name(merged, "Ai+"))
        self.assertIsNone(clash._group_by_name(merged, "Ai稳定选择"))
        targets = {rule.split(",")[2] for rule in merged["rules"] if len(rule.split(",")) > 2}
        self.assertTrue(targets <= {"DIRECT", "REJECT"})
        self.assertIn("DOMAIN-SUFFIX,tailscale.io,DIRECT", merged["rules"])
        self.assertEqual(merged["rules"][-1], "MATCH,漏网之鱼")

    def test_referenced_legacy_group_is_kept(self):
        # Regression: Ai自动选择 used to be dropped unconditionally, which broke
        # any subscription still pointing at it from a group or a rule.
        config = sample_config()
        config["proxy-groups"].append(
            {"name": "AI专用", "type": "select", "proxies": ["Ai自动选择"]}
        )
        config["proxy-groups"].append(
            {"name": "Ai自动选择", "type": "url-test", "proxies": ["🇺🇸 美国-01"]}
        )
        config["rules"].insert(-1, "DOMAIN,example.org,Ai自动选择")

        merged = clash.apply_customizations(config, self.rule_sets)
        self.assertIsNotNone(clash._group_by_name(merged, "Ai自动选择"))
        self.assertIn("DOMAIN,example.org,Ai自动选择", merged["rules"])
        group_names = [group["name"] for group in merged["proxy-groups"]]
        self.assertEqual(len(group_names), len(set(group_names)))
        # A single pass, so the untouched legacy group survives once.
        self.assertEqual(group_names.count("Ai自动选择"), 1)

    def test_unreferenced_legacy_group_is_still_removed(self):
        merged = clash.apply_customizations(sample_config(), self.rule_sets)
        self.assertIsNone(clash._group_by_name(merged, "Ai自动选择"))

    def test_subscription_without_proxy_groups_degrades(self):
        config = {"rules": ["MATCH,DIRECT"]}
        merged = clash.apply_customizations(config, self.rule_sets)
        self.assertNotIn("proxy-groups", merged)
        targets = {rule.split(",")[2] for rule in merged["rules"] if len(rule.split(",")) > 2}
        self.assertTrue(targets <= {"DIRECT", "REJECT"})
        self.assertEqual(merged["rules"][-1], "MATCH,DIRECT")


class ScriptGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule_sets = clash.load_rule_sets()

    def test_script_is_generated_without_subscription_or_secrets(self):
        script = clash.render_override_script(self.rule_sets)
        self.assertIn("function main(config)", script)
        self.assertIn('"DOMAIN,scholar.google.com,学术搜索"', script)
        self.assertIn('"DOMAIN-SUFFIX,google.com,Ai+"', script)
        self.assertIn('"DOMAIN-SUFFIX,claude.ai,Ai+"', script)
        self.assertIn('"DOMAIN-SUFFIX,github.com,Ai+"', script)
        self.assertIn('"DOMAIN-SUFFIX,science.org,学术访问"', script)
        self.assertIn('"DOMAIN-SUFFIX,adobedtm.com,DIRECT"', script)
        self.assertNotIn('"DOMAIN,www.google.com,Ai+"', script)
        self.assertNotIn("__CUSTOM_RULES_JSON__", script)
        self.assertNotIn("proxy-providers:", script)

    def test_atomic_text_writer_round_trips_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "override.js"
            clash.write_text_atomic(target, "const group = '学术搜索';\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "const group = '学术搜索';\n")


class ServerPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule_sets = clash.load_rule_sets()
        cls.policy = clash.build_server_policy(cls.rule_sets)

    def groups(self):
        return {group["name"]: group for group in self.policy["proxy-groups"]}

    def test_server_mirrors_the_desktop_ai_shape(self):
        groups = self.groups()
        self.assertEqual(
            sorted(groups),
            sorted(["PROXY", "Ai稳定选择", "Ai测速备用", "Ai+", "Dev+", "学术搜索", "学术访问"]),
        )
        for name in ("Ai稳定选择", "Ai测速备用", "Dev+"):
            self.assertEqual(groups[name]["use"], ["subscription"])
            self.assertEqual(groups[name]["exclude-filter"], clash.AI_EXCLUDE_FILTER)
        self.assertEqual(groups["Ai稳定选择"]["type"], "select")
        self.assertEqual(groups["Ai稳定选择"]["filter"], clash.AI_INCLUDE_FILTER)
        self.assertEqual(groups["Ai测速备用"]["type"], "url-test")
        self.assertEqual(groups["Ai测速备用"]["url"], clash.AI_PROBE_URL)
        self.assertEqual(groups["Ai测速备用"]["expected-status"], 200)
        self.assertEqual(groups["Ai+"]["proxies"], ["Ai稳定选择", "Ai测速备用"])
        self.assertEqual(groups["学术搜索"]["proxies"], ["Ai+", "DIRECT"])
        self.assertEqual(groups["学术访问"]["proxies"], ["DIRECT", "Ai+"])

    def test_dev_group_accepts_us_and_hong_kong(self):
        dev = self.groups()["Dev+"]
        self.assertEqual(dev["filter"], clash.DEV_INCLUDE_FILTER)
        self.assertEqual(dev["proxies"], ["PROXY"])
        self.assertEqual(self.groups()["PROXY"]["url"], clash.GENERIC_PROBE_URL)

    def test_server_rules_only_use_server_targets(self):
        rules = self.policy["rules"]
        self.assertEqual(rules[-1], "MATCH,DIRECT")
        self.assertIn(
            "DOMAIN,sea-ad-single-cell-profiling.s3.amazonaws.com,DIRECT", rules
        )
        self.assertIn("DOMAIN-SUFFIX,ncbi.nlm.nih.gov,DIRECT", rules)
        self.assertIn("DOMAIN-SUFFIX,github.com,Dev+", rules)
        self.assertIn("DOMAIN-SUFFIX,claude.ai,Ai+", rules)
        # Desktop-only rule-sets are trimmed away.
        for gone in ("adobedtm.com", "bing.com", "doubleclick.net", "tailscale.io"):
            self.assertFalse(any(gone in rule for rule in rules), gone)

    def test_rendered_policy_is_secret_free_and_anchor_free(self):
        rendered = clash.render_server_policy(self.rule_sets)
        self.assertNotIn("proxy-providers:", rendered)
        self.assertNotRegex(rendered, r"(?i)(subscription[_-]?url|password|secret|token):")
        # Reused dicts must not leak YAML anchors into a hand-edited file.
        self.assertNotIn("&id0", rendered)
        self.assertNotIn("*id0", rendered)

    def test_rendered_policy_round_trips_filters_exactly(self):
        # A folded long line would silently insert a space into the regex.
        parsed = yaml.safe_load(clash.render_server_policy(self.rule_sets))
        groups = {group["name"]: group for group in parsed["proxy-groups"]}
        self.assertEqual(groups["Ai稳定选择"]["filter"], clash.AI_INCLUDE_FILTER)
        self.assertEqual(groups["Ai测速备用"]["filter"], clash.AI_INCLUDE_FILTER)
        self.assertEqual(groups["Dev+"]["filter"], clash.DEV_INCLUDE_FILTER)
        self.assertEqual(groups["Ai稳定选择"]["exclude-filter"], clash.AI_EXCLUDE_FILTER)


if __name__ == "__main__":
    unittest.main()
