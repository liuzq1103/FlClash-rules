import argparse
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import yaml


BASE_DIR = Path(__file__).resolve().parent
RULES_DIR = BASE_DIR / "rules"
RULES_INDEX = RULES_DIR / "index.yml"
TEMPLATE_PATH = BASE_DIR / "templates" / "override.js.tpl"
DEFAULT_SCRIPT_OUTPUT = BASE_DIR / "dist" / "override.js"
DEFAULT_SOURCE = BASE_DIR / "local" / "gw树洞.yaml"
DEFAULT_OUTPUT_DIR = BASE_DIR / "local" / "output"
OUTPUT_PREFIX = "merged_"

AI_GROUP = "Ai+"
AI_STABLE_GROUP = "Ai稳定选择"
AI_AUTO_GROUP = "Ai测速备用"
LEGACY_AI_AUTO_GROUP = "Ai自动选择"
SCHOLAR_GROUP = "学术搜索"
FALLBACK_GROUP = "漏网之鱼"
CUSTOM_PROVIDER_PREFIX = "Custom-"

BUILTIN_TARGETS = {
    "DIRECT",
    "REJECT",
    "REJECT-DROP",
    "PASS",
    "COMPATIBLE",
}

SUPPORTED_RULE_TYPES = {
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "DOMAIN-WILDCARD",
    "DOMAIN-REGEX",
    "IP-CIDR",
    "IP-CIDR6",
    "SRC-IP-CIDR",
    "DST-PORT",
    "SRC-PORT",
    "PROCESS-NAME",
    "PROCESS-PATH",
    "NETWORK",
    "GEOIP",
    "GEOSITE",
}

# Keep short country codes bounded so
# ordinary node names containing "tw", "hk", or "mo" are not false matches.
AI_EXCLUDE_FILTER = (
    r"(?i)(?:🇭🇰|🇲🇴|🇹🇼|香港|澳门|澳門|台湾|台灣|"
    r"hong[ -]?kong|macau|macao|taiwan|"
    r"(?:^|[^a-z])(?:hk|mo|tw)(?:[^a-z]|$)|"
    r"剩余流量|流量剩余|到期时间|过期时间|重置时间|套餐提示|订阅信息|"
    r"(?:^|[\s|_-])(?:expire|traffic|sync|reset|官网|套餐|订阅|更新|客服|网址)"
    r"(?:[\s:：|_-]|$))"
)


class ConfigError(ValueError):
    """Raised when a source configuration or custom rule is invalid."""


def load_yaml(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data or {}


def _parse_payload_rule(rule, source_label):
    if not isinstance(rule, str) or not rule.strip():
        raise ConfigError(f"{source_label}: payload entries must be non-empty strings")

    parts = [part.strip() for part in rule.split(",")]
    if len(parts) < 2:
        raise ConfigError(f"{source_label}: invalid rule: {rule}")

    rule_type = parts[0].upper()
    if rule_type not in SUPPORTED_RULE_TYPES:
        raise ConfigError(f"{source_label}: unsupported rule type {rule_type}: {rule}")
    if not parts[1]:
        raise ConfigError(f"{source_label}: empty rule value: {rule}")
    if any(part in BUILTIN_TARGETS or part in {AI_GROUP, FALLBACK_GROUP} for part in parts[2:]):
        raise ConfigError(
            f"{source_label}: provider payload must not contain a policy target: {rule}"
        )
    if len(parts) > 2 and parts[-1] != "no-resolve":
        raise ConfigError(f"{source_label}: unsupported rule option: {rule}")
    if parts[-1] == "no-resolve" and rule_type not in {
        "IP-CIDR",
        "IP-CIDR6",
        "SRC-IP-CIDR",
        "GEOIP",
    }:
        raise ConfigError(f"{source_label}: no-resolve is only valid for IP rules: {rule}")

    return rule_type, parts[1].lower().strip("."), rule.strip()


def _rule_shadows(earlier, later):
    earlier_type, earlier_value, _ = earlier
    later_type, later_value, _ = later

    if earlier_type == "DOMAIN-SUFFIX" and later_type in {"DOMAIN", "DOMAIN-SUFFIX"}:
        return later_value == earlier_value or later_value.endswith("." + earlier_value)
    if earlier_type == "DOMAIN" and later_type == "DOMAIN":
        return earlier_value == later_value
    if earlier_type == "DOMAIN-KEYWORD" and later_type.startswith("DOMAIN"):
        return earlier_value in later_value
    return False


def load_rule_sets(index_path=RULES_INDEX):
    index_path = Path(index_path)
    index = load_yaml(index_path)
    definitions = index.get("rule-sets")
    if not isinstance(definitions, list) or not definitions:
        raise ConfigError(f"{index_path}: rule-sets must be a non-empty list")

    names = set()
    files = set()
    exact_rules = {}
    parsed_rules = []
    rule_targets = {}
    rule_sets = []

    for position, definition in enumerate(definitions, start=1):
        if not isinstance(definition, dict):
            raise ConfigError(f"{index_path}: rule-set #{position} must be a mapping")

        name = definition.get("name")
        file_name = definition.get("file")
        target = definition.get("target")
        if not all(isinstance(value, str) and value for value in (name, file_name, target)):
            raise ConfigError(f"{index_path}: rule-set #{position} requires name, file, target")
        if not name.startswith(CUSTOM_PROVIDER_PREFIX):
            raise ConfigError(f"{index_path}: custom provider must start with {CUSTOM_PROVIDER_PREFIX}: {name}")
        if name in names:
            raise ConfigError(f"{index_path}: duplicate provider name: {name}")
        if file_name in files:
            raise ConfigError(f"{index_path}: duplicate rule file: {file_name}")

        rule_path = (index_path.parent / file_name).resolve()
        if rule_path.parent != index_path.parent.resolve():
            raise ConfigError(f"{index_path}: rule file must stay inside rules/: {file_name}")
        if not rule_path.is_file():
            raise ConfigError(f"{index_path}: missing rule file: {file_name}")

        content = load_yaml(rule_path)
        payload = content.get("payload")
        if not isinstance(payload, list) or not payload:
            raise ConfigError(f"{rule_path}: payload must be a non-empty list")

        normalized_payload = []
        for line_number, raw_rule in enumerate(payload, start=1):
            parsed = _parse_payload_rule(raw_rule, f"{rule_path}:{line_number}")
            normalized = parsed[2]
            if normalized in exact_rules:
                raise ConfigError(
                    f"duplicate rule in {rule_path}:{line_number}; first seen in {exact_rules[normalized]}: "
                    f"{normalized}"
                )

            for earlier in parsed_rules:
                if earlier[3] == target and _rule_shadows(earlier[:3], parsed):
                    raise ConfigError(
                        f"redundant rule in {rule_path}:{line_number}: {normalized}; "
                        f"covered by {earlier[2]}"
                    )

            exact_rules[normalized] = f"{rule_path}:{line_number}"
            parsed_rules.append((parsed[0], parsed[1], parsed[2], target))
            rule_targets[normalized] = target
            normalized_payload.append(normalized)

        names.add(name)
        files.add(file_name)
        rule_sets.append(
            {
                "name": name,
                "file": file_name,
                "target": target,
                "payload": normalized_payload,
            }
        )

    constraints = index.get("route-constraints", [])
    if not isinstance(constraints, list):
        raise ConfigError(f"{index_path}: route-constraints must be a list")
    constraint_names = set()
    for position, constraint in enumerate(constraints, start=1):
        if not isinstance(constraint, dict):
            raise ConfigError(f"{index_path}: route-constraint #{position} must be a mapping")
        constraint_name = constraint.get("name")
        constraint_target = constraint.get("target")
        constraint_rules = constraint.get("rules")
        if not isinstance(constraint_name, str) or not constraint_name:
            raise ConfigError(f"{index_path}: route-constraint #{position} requires a name")
        if constraint_name in constraint_names:
            raise ConfigError(f"{index_path}: duplicate route-constraint: {constraint_name}")
        if not isinstance(constraint_target, str) or not constraint_target:
            raise ConfigError(f"{index_path}: route-constraint {constraint_name} requires a target")
        if not isinstance(constraint_rules, list) or not constraint_rules:
            raise ConfigError(f"{index_path}: route-constraint {constraint_name} requires rules")
        for constrained_rule in constraint_rules:
            if not isinstance(constrained_rule, str) or not constrained_rule:
                raise ConfigError(
                    f"{index_path}: route-constraint {constraint_name} has an invalid rule"
                )
            actual_target = rule_targets.get(constrained_rule)
            if actual_target is None:
                raise ConfigError(
                    f"{index_path}: route-constraint {constraint_name} references a missing rule: "
                    f"{constrained_rule}"
                )
            if actual_target != constraint_target:
                raise ConfigError(
                    f"{index_path}: route-constraint {constraint_name} requires "
                    f"{constrained_rule} -> {constraint_target}, found {actual_target}"
                )
        constraint_names.add(constraint_name)

    return rule_sets


def _group_by_name(config, name):
    for group in config.get("proxy-groups", []):
        if group.get("name") == name:
            return group
    return None


def configure_ai_groups(config):
    groups = config.get("proxy-groups")
    if not isinstance(groups, list):
        raise ConfigError("source config must contain a proxy-groups list")

    ai_group = _group_by_name(config, AI_GROUP)
    if ai_group is None:
        raise ConfigError(f"source config is missing required proxy group: {AI_GROUP}")

    groups[:] = [
        group
        for group in groups
        if group.get("name")
        not in {AI_STABLE_GROUP, AI_AUTO_GROUP, LEGACY_AI_AUTO_GROUP, SCHOLAR_GROUP}
    ]
    ai_index = groups.index(ai_group)

    proxies = config.get("proxies")
    if not isinstance(proxies, list):
        raise ConfigError("source config must contain a proxies list")
    excluded = re.compile(AI_EXCLUDE_FILTER)
    ai_candidates = [
        proxy["name"]
        for proxy in proxies
        if isinstance(proxy, dict)
        and isinstance(proxy.get("name"), str)
        and proxy["name"]
        and not excluded.search(proxy["name"])
        and str(proxy.get("type", "")).lower() != "direct"
    ]
    if not ai_candidates:
        raise ConfigError(f"no eligible nodes remain for {AI_AUTO_GROUP}")

    ai_stable = {
        "name": AI_STABLE_GROUP,
        "type": "select",
        "proxies": ai_candidates,
    }
    ai_auto = {
        "name": AI_AUTO_GROUP,
        "type": "url-test",
        "proxies": ai_candidates,
        "url": "https://chatgpt.com/cdn-cgi/trace",
        "interval": 300,
        "tolerance": 50,
        "lazy": True,
        "timeout": 8000,
        "max-failed-times": 2,
        "expected-status": 200,
    }
    scholar = {
        "name": SCHOLAR_GROUP,
        "type": "select",
        "proxies": [AI_STABLE_GROUP, AI_AUTO_GROUP],
    }
    groups[ai_index:ai_index] = [ai_stable, ai_auto, scholar]

    # Explicit node lists avoid runtime compatibility problems in FlClash
    # versions that display newer dynamic fields but do not preserve them.
    ai_group["proxies"] = [AI_STABLE_GROUP, AI_AUTO_GROUP]
    for key in (
        "include-all",
        "include-all-proxies",
        "include-all-providers",
        "filter",
        "exclude-filter",
        "exclude-type",
        "default-selected",
        "empty-fallback",
    ):
        ai_group.pop(key, None)

    fallback = _group_by_name(config, FALLBACK_GROUP)
    if fallback is None:
        raise ConfigError(f"source config is missing required proxy group: {FALLBACK_GROUP}")
    choices = [choice for choice in fallback.get("proxies", []) if choice != "DIRECT"]
    fallback["proxies"] = ["DIRECT"] + choices
    fallback.pop("default-selected", None)


def fix_provider_paths(config):
    providers = config.get("rule-providers")
    if not isinstance(providers, dict):
        raise ConfigError("source config must contain a rule-providers mapping")

    apple = providers.get("Apple")
    apple_dev = providers.get("AppleDev")
    if isinstance(apple, dict) and isinstance(apple_dev, dict):
        if apple.get("path") and apple.get("path") == apple_dev.get("path"):
            apple["path"] = "./providers/rule/Apple.yaml"


def _expand_custom_rules(rule_sets):
    expanded = []
    for rule_set in rule_sets:
        for payload_rule in rule_set["payload"]:
            parts = [part.strip() for part in payload_rule.split(",")]
            if parts[-1] == "no-resolve":
                parts.insert(-1, rule_set["target"])
            else:
                parts.append(rule_set["target"])
            expanded.append(",".join(parts))
    return expanded


def _rule_match_key(rule):
    if not isinstance(rule, str):
        return None
    parts = [part.strip() for part in rule.split(",")]
    if len(parts) < 2 or parts[0].upper() not in SUPPORTED_RULE_TYPES:
        return None
    key = parts[:2]
    if parts[-1] == "no-resolve":
        key.append("no-resolve")
    return ",".join(key)


def merge_custom_rules(config, rule_sets):
    providers = config.setdefault("rule-providers", {})
    if not isinstance(providers, dict):
        raise ConfigError("source rule-providers must be a mapping")

    for name in list(providers):
        if name.startswith(CUSTOM_PROVIDER_PREFIX):
            del providers[name]

    source_rules = config.get("rules")
    if not isinstance(source_rules, list):
        raise ConfigError("source config must contain a rules list")
    custom_rules = _expand_custom_rules(rule_sets)
    custom_rule_set = set(custom_rules)
    custom_match_keys = {
        _rule_match_key(rule)
        for rule_set in rule_sets
        for rule in rule_set["payload"]
    }
    source_rules = [
        rule
        for rule in source_rules
        if not (
            isinstance(rule, str)
            and (
                rule.startswith("RULE-SET," + CUSTOM_PROVIDER_PREFIX)
                or rule in custom_rule_set
                or _rule_match_key(rule) in custom_match_keys
            )
        )
    ]
    config["rules"] = custom_rules + source_rules


def apply_customizations(source_config, rule_sets):
    config = copy.deepcopy(source_config)
    fix_provider_paths(config)
    configure_ai_groups(config)
    merge_custom_rules(config, rule_sets)
    validate_config(config, rule_sets)
    return config


def _rule_target(rule):
    parts = [part.strip() for part in rule.split(",")]
    if not parts:
        return None
    if parts[0] == "MATCH":
        return parts[1] if len(parts) > 1 else None
    return parts[2] if len(parts) > 2 else None


def validate_config(config, rule_sets):
    if not isinstance(config, dict):
        raise ConfigError("configuration root must be a mapping")

    groups = config.get("proxy-groups")
    proxies = config.get("proxies")
    providers = config.get("rule-providers")
    rules = config.get("rules")
    if not isinstance(groups, list) or not isinstance(proxies, list):
        raise ConfigError("configuration requires proxies and proxy-groups lists")
    if not isinstance(providers, dict) or not isinstance(rules, list):
        raise ConfigError("configuration requires rule-providers and rules")

    group_names = [group.get("name") for group in groups]
    if len(group_names) != len(set(group_names)):
        raise ConfigError("proxy group names must be unique")

    proxy_names = {
        proxy.get("name") for proxy in proxies if isinstance(proxy, dict) and proxy.get("name")
    }
    valid_targets = set(group_names) | proxy_names | BUILTIN_TARGETS

    seen_paths = {}
    for name, provider in providers.items():
        if not isinstance(provider, dict):
            raise ConfigError(f"rule provider must be a mapping: {name}")
        path = provider.get("path")
        if path:
            if path in seen_paths:
                raise ConfigError(
                    f"duplicate rule-provider path {path}: {seen_paths[path]} and {name}"
                )
            seen_paths[path] = name

    for rule in rules:
        if not isinstance(rule, str):
            raise ConfigError(f"rule must be a string: {rule!r}")
        parts = [part.strip() for part in rule.split(",")]
        if parts[0] == "RULE-SET":
            if len(parts) < 3 or parts[1] not in providers:
                raise ConfigError(f"rule references missing provider: {rule}")
        target = _rule_target(rule)
        if target and target not in valid_targets:
            raise ConfigError(f"rule references missing policy target {target}: {rule}")

    expected_prefix = _expand_custom_rules(rule_sets)
    if rules[: len(expected_prefix)] != expected_prefix:
        raise ConfigError("custom rules are not at the beginning in the declared priority order")
    if not rules or not rules[-1].startswith("MATCH,"):
        raise ConfigError("the final source rule must remain MATCH")

    ai_stable = _group_by_name(config, AI_STABLE_GROUP)
    ai_auto = _group_by_name(config, AI_AUTO_GROUP)
    ai_group = _group_by_name(config, AI_GROUP)
    scholar = _group_by_name(config, SCHOLAR_GROUP)
    fallback = _group_by_name(config, FALLBACK_GROUP)
    if not ai_stable or not ai_stable.get("proxies"):
        raise ConfigError(f"{AI_STABLE_GROUP} must contain explicit proxy nodes")
    if not ai_auto or not ai_auto.get("proxies"):
        raise ConfigError(f"{AI_AUTO_GROUP} must contain explicit proxy nodes")
    if not ai_group or ai_group.get("proxies") != [AI_STABLE_GROUP, AI_AUTO_GROUP]:
        raise ConfigError(f"{AI_GROUP} must prefer stable selection and keep auto as backup")
    if not scholar or scholar.get("proxies") != [AI_STABLE_GROUP, AI_AUTO_GROUP]:
        raise ConfigError(f"{SCHOLAR_GROUP} must share the stable AI exit")
    if not fallback or fallback.get("proxies", [None])[0] != "DIRECT":
        raise ConfigError(f"{FALLBACK_GROUP} must list DIRECT first")


def write_yaml_atomic(output_path, data):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(output_path.parent),
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)

        load_yaml(temp_path)
        os.replace(str(temp_path), str(output_path))
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def write_text_atomic(output_path, text):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=str(output_path.parent),
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
        if temp_path.read_text(encoding="utf-8") != text:
            raise ConfigError(f"failed to verify generated text: {output_path}")
        os.replace(str(temp_path), str(output_path))
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def render_override_script(rule_sets, template_path=TEMPLATE_PATH):
    template_path = Path(template_path)
    if not template_path.is_file():
        raise ConfigError(f"extension template not found: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    marker = "__CUSTOM_RULES_JSON__"
    if template.count(marker) != 1:
        raise ConfigError(f"extension template must contain exactly one {marker} marker")
    rules_json = json.dumps(
        _expand_custom_rules(rule_sets), ensure_ascii=False, indent=2
    )
    script = template.replace(marker, rules_json)
    if marker in script or "function main(config)" not in script:
        raise ConfigError("generated extension script is incomplete")
    return script.rstrip() + "\n"


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Build a Clash Verge Rev subscription extension from maintainable rules."
    )
    parser.add_argument(
        "source",
        nargs="?",
        help=f"subscription YAML for --legacy-merge (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the rules and source subscription without writing output",
    )
    parser.add_argument(
        "--check-rules",
        action="store_true",
        help="validate only the tracked rule files (used by GitHub Actions)",
    )
    parser.add_argument(
        "--legacy-merge",
        action="store_true",
        help="emergency fallback: generate a complete merged YAML",
    )
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    try:
        rule_sets = load_rule_sets()
        rule_count = sum(len(rule_set["payload"]) for rule_set in rule_sets)
        if args.check_rules:
            print(f"Rule validation passed: {len(rule_sets)} sets, {rule_count} rules")
            return 0

        if args.source and not args.legacy_merge:
            raise ConfigError("a subscription path is only valid with --legacy-merge")

        script = render_override_script(rule_sets)
        if args.check:
            if not DEFAULT_SCRIPT_OUTPUT.is_file():
                raise ConfigError(f"generated extension is missing: {DEFAULT_SCRIPT_OUTPUT}")
            if DEFAULT_SCRIPT_OUTPUT.read_text(encoding="utf-8") != script:
                raise ConfigError("dist/override.js is stale; run: python clash.py")
            compatibility = ""
            if DEFAULT_SOURCE.is_file():
                apply_customizations(load_yaml(DEFAULT_SOURCE), rule_sets)
                compatibility = "; local subscription compatible"
            print(f"Extension validation passed: {rule_count} rules{compatibility}")
            return 0

        if args.legacy_merge:
            source_path = Path(args.source).resolve() if args.source else DEFAULT_SOURCE
            if not source_path.is_file():
                raise ConfigError(
                    f"subscription not found: {source_path}\n"
                    f"Place it at {DEFAULT_SOURCE} or pass a path after --legacy-merge."
                )
            merged = apply_customizations(load_yaml(source_path), rule_sets)
            output_path = DEFAULT_OUTPUT_DIR / f"{OUTPUT_PREFIX}{source_path.name}"
            write_yaml_atomic(output_path, merged)
            print(f"Emergency merged configuration saved to: {output_path}")
            return 0

        write_text_atomic(DEFAULT_SCRIPT_OUTPUT, script)
        print(f"Subscription extension saved to: {DEFAULT_SCRIPT_OUTPUT}")
        return 0
    except (ConfigError, OSError, yaml.YAMLError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
