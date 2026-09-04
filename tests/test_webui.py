import tempfile
import unittest
from pathlib import Path

import clash
import webui


def write_rules_tree(root):
    (root / "site.yaml").write_text(
        "payload:\n"
        "  # a comment that must survive\n"
        "  - DOMAIN-SUFFIX,old.test\n",
        encoding="utf-8",
    )
    (root / "index.yml").write_text(
        "rule-sets:\n"
        "  - name: Custom-Site\n"
        "    file: site.yaml\n"
        "    target: DIRECT\n",
        encoding="utf-8",
    )
    return root / "index.yml"


class ExtractHostTests(unittest.TestCase):
    def test_extracts_host_from_urls_and_bare_domains(self):
        cases = {
            "https://www.nature.com/articles/s41586": "nature.com",
            "nature.com": "nature.com",
            "https://Chat.OpenAI.com:8443/x?a=b": "chat.openai.com",
            "  https://www.pku.edu.cn/admission  ": "pku.edu.cn",
            "www.example.com/path": "example.com",
            "https://a.com/x extra tokens": "a.com",
            "example.org.:443/x": "example.org",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(webui.extract_host(text), expected)

    def test_returns_none_for_invalid_input(self):
        for text in ["", "   ", "https://", "://", "http:///path", "https://:8080"]:
            with self.subTest(text=text):
                self.assertIsNone(webui.extract_host(text))

    def test_non_string_input_returns_none(self):
        self.assertIsNone(webui.extract_host(None))
        self.assertIsNone(webui.extract_host(123))


class RegistrableDomainTests(unittest.TestCase):
    def test_multi_part_suffixes(self):
        cases = {
            "www.pku.edu.cn": "pku.edu.cn",
            "a.b.co.uk": "b.co.uk",
            "x.y.ac.cn": "y.ac.cn",
        }
        for host, expected in cases.items():
            with self.subTest(host=host):
                self.assertEqual(webui.registrable_domain(host), expected)

    def test_plain_domains(self):
        self.assertEqual(webui.registrable_domain("chat.openai.com"), "openai.com")
        self.assertEqual(webui.registrable_domain("nature.com"), "nature.com")

    def test_single_label_returns_none(self):
        self.assertIsNone(webui.registrable_domain("localhost"))


class BuildCandidatesTests(unittest.TestCase):
    def test_domain_url_yields_candidates_with_suffix_first(self):
        host, candidates = webui.build_candidates(
            "https://www.nature.com/articles/s41586"
        )
        self.assertEqual(host, "nature.com")
        rules = [item["rule"] for item in candidates]
        self.assertEqual(rules[0], "DOMAIN-SUFFIX,nature.com")
        self.assertIn("DOMAIN,nature.com", rules)
        self.assertIn("DOMAIN-KEYWORD,nature.com", rules)

    def test_subdomain_url_includes_exact_host(self):
        host, candidates = webui.build_candidates("https://chat.openai.com/c/123")
        self.assertEqual(host, "chat.openai.com")
        rules = [item["rule"] for item in candidates]
        self.assertEqual(rules[0], "DOMAIN-SUFFIX,openai.com")
        self.assertIn("DOMAIN,chat.openai.com", rules)

    def test_ip_input_yields_cidr_candidate(self):
        host, candidates = webui.build_candidates("https://1.2.3.4/x")
        self.assertEqual(host, "1.2.3.4")
        self.assertEqual(candidates[0]["rule"], "IP-CIDR,1.2.3.4")

        host6, candidates6 = webui.build_candidates("http://[2001:db8::1]/")
        self.assertEqual(candidates6[0]["rule"], "IP-CIDR6,2001:db8::1")

    def test_empty_input_raises(self):
        with self.assertRaises(clash.ConfigError):
            webui.build_candidates("   ")


class InspectRuleTests(unittest.TestCase):
    def test_exact_duplicate_is_blocked(self):
        result = webui.inspect_rule("DOMAIN-SUFFIX,science.org", "direct.yaml")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("academic.yaml", result["message"])

    def test_covered_by_earlier_rule_is_blocked(self):
        result = webui.inspect_rule("DOMAIN,github.com", "direct.yaml")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("ai.yaml", result["message"])

    def test_fresh_rule_is_ok(self):
        result = webui.inspect_rule("DOMAIN-SUFFIX,brand-new-site.test", "direct.yaml")
        self.assertEqual(result["status"], "ok")

    def test_shadowing_later_rule_with_same_target_is_blocked(self):
        # tailscale.yaml comes before direct.yaml and both target DIRECT, so a
        # covering suffix there would make direct.yaml's entry redundant.
        result = webui.inspect_rule(
            "DOMAIN-SUFFIX,s3.amazonaws.com", "tailscale.yaml"
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("direct.yaml", result["message"])

    def test_shadowing_later_rule_with_different_target_warns(self):
        result = webui.inspect_rule("DOMAIN-SUFFIX,s3.amazonaws.com", "ai.yaml")
        self.assertEqual(result["status"], "warn")
        self.assertIn("direct.yaml", result["warning"])

    def test_unknown_file_is_blocked(self):
        result = webui.inspect_rule("DOMAIN-SUFFIX,x.test", "nope.yaml")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("未知", result["message"])

    def test_invalid_rule_is_blocked(self):
        result = webui.inspect_rule("NOT-A-TYPE,x", "direct.yaml")
        self.assertEqual(result["status"], "blocked")

    def test_payload_with_target_is_blocked(self):
        result = webui.inspect_rule("DOMAIN-SUFFIX,x.test,DIRECT", "direct.yaml")
        self.assertEqual(result["status"], "blocked")


class AppendRuleTests(unittest.TestCase):
    def test_appends_and_preserves_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            index_path = write_rules_tree(Path(directory))
            normalized = webui.append_rule(
                "DOMAIN-SUFFIX,new.test", "site.yaml", index_path=index_path
            )
            self.assertEqual(normalized, "DOMAIN-SUFFIX,new.test")
            text = (index_path.parent / "site.yaml").read_text(encoding="utf-8")
            self.assertIn("# a comment that must survive", text)
            self.assertIn("  - DOMAIN-SUFFIX,new.test\n", text)
            rule_sets = clash.load_rule_sets(index_path)
            self.assertIn("DOMAIN-SUFFIX,new.test", rule_sets[0]["payload"])

    def test_duplicate_append_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index_path = write_rules_tree(root)
            original = (root / "site.yaml").read_bytes()
            with self.assertRaises(clash.ConfigError):
                webui.append_rule(
                    "DOMAIN-SUFFIX,old.test", "site.yaml", index_path=index_path
                )
            self.assertEqual((root / "site.yaml").read_bytes(), original)

    def test_append_without_payload_tail_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "site.yaml").write_text(
                "payload:\n  - DOMAIN-SUFFIX,old.test\nnotes: extra\n",
                encoding="utf-8",
            )
            (root / "index.yml").write_text(
                "rule-sets:\n"
                "  - name: Custom-Site\n"
                "    file: site.yaml\n"
                "    target: DIRECT\n",
                encoding="utf-8",
            )
            original = (root / "site.yaml").read_bytes()
            with self.assertRaises(clash.ConfigError):
                webui.append_rule(
                    "DOMAIN-SUFFIX,new.test",
                    "site.yaml",
                    index_path=root / "index.yml",
                )
            self.assertEqual((root / "site.yaml").read_bytes(), original)

    def test_append_landing_outside_payload_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "site.yaml").write_text(
                "payload:\n  - DOMAIN-SUFFIX,old.test\nother:\n  - stray\n",
                encoding="utf-8",
            )
            (root / "index.yml").write_text(
                "rule-sets:\n"
                "  - name: Custom-Site\n"
                "    file: site.yaml\n"
                "    target: DIRECT\n",
                encoding="utf-8",
            )
            original = (root / "site.yaml").read_bytes()
            with self.assertRaises(clash.ConfigError):
                webui.append_rule(
                    "DOMAIN-SUFFIX,new.test",
                    "site.yaml",
                    index_path=root / "index.yml",
                )
            self.assertEqual((root / "site.yaml").read_bytes(), original)

    def test_unknown_file_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            index_path = write_rules_tree(Path(directory))
            with self.assertRaises(clash.ConfigError):
                webui.append_rule(
                    "DOMAIN-SUFFIX,new.test", "nope.yaml", index_path=index_path
                )


class StateAndBuildTests(unittest.TestCase):
    def test_collect_state_lists_all_rule_files(self):
        state = webui.collect_state()
        self.assertEqual(
            [item["file"] for item in state["files"]],
            [
                "reject.yaml",
                "ai.yaml",
                "scholar.yaml",
                "academic.yaml",
                "tailscale.yaml",
                "direct.yaml",
            ],
        )
        self.assertEqual(
            state["total"], sum(item["count"] for item in state["files"])
        )
        self.assertIn("stale", state["dist"])
        self.assertIn("exists", state["dist"])

    def test_build_extension_matches_clash_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "override.js"
            result = webui.build_extension(output_path=output)
            expected = clash.render_override_script(clash.load_rule_sets())
            self.assertEqual(output.read_text(encoding="utf-8"), expected)
            expected_count = sum(
                len(rule_set["payload"]) for rule_set in clash.load_rule_sets()
            )
            self.assertEqual(result["count"], expected_count)
            self.assertEqual(result["path"], str(output))


if __name__ == "__main__":
    unittest.main()
