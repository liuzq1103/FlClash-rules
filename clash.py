import argparse
import copy
import os
import sys
import tempfile
from pathlib import Path

import yaml


BASE_DIR = Path(__file__).resolve().parent
RULES_DIR = BASE_DIR / "rules"
RULES_INDEX = RULES_DIR / "index.yml"
DEFAULT_SOURCE = BASE_DIR / "local" / "gw树洞.yaml"
DEFAULT_OUTPUT_DIR = BASE_DIR / "local" / "output"
OUTPUT_PREFIX = "merged_"

AI_GROUP = "Ai+"
AI_AUTO_GROUP = "Ai自动选择"
MANUAL_GROUP = "手动选择"
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

# Go regular expression used by Mihomo. Short country codes are bounded so
# ordinary node names containing "tw", "hk", or "mo" are not false matches.
AI_EXCLUDE_FILTER = (
    r"(?i)(?:🇭🇰|🇲🇴|🇹🇼|香港|澳门|澳門|台湾|台灣|"
    r"hong[ -]?kong|macau|macao|taiwan|"
    r"(?:^|[^a-z])(?:hk|mo|tw)(?:[^a-z]|$)|"
    r"^(?:expire|traffic|sync):|官网)"
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

    groups[:] = [group for group in groups if group.get("name") != AI_AUTO_GROUP]
    ai_index = groups.index(ai_group)
    ai_auto = {
        "name": AI_AUTO_GROUP,
        "type": "url-test",
        "include-all-proxies": True,
        "exclude-filter": AI_EXCLUDE_FILTER,
        "exclude-type": "direct",
        "url": "http://www.gstatic.com/generate_204",
        "interval": 300,
        "tolerance": 20,
        "lazy": True,
        "expected-status": 204,
    }
    groups.insert(ai_index, ai_auto)

    explicit_choices = [AI_AUTO_GROUP]
    if _group_by_name(config, MANUAL_GROUP) is not None:
        explicit_choices.append(MANUAL_GROUP)
    ai_group["proxies"] = explicit_choices
    ai_group["include-all-proxies"] = True
    ai_group["exclude-filter"] = AI_EXCLUDE_FILTER
    ai_group["exclude-type"] = "direct"
    ai_group["default-selected"] = AI_AUTO_GROUP

    fallback = _group_by_name(config, FALLBACK_GROUP)
    if fallback is None:
        raise ConfigError(f"source config is missing required proxy group: {FALLBACK_GROUP}")
    choices = [choice for choice in fallback.get("proxies", []) if choice != "DIRECT"]
    fallback["proxies"] = ["DIRECT"] + choices
    fallback["default-selected"] = "DIRECT"


def fix_provider_paths(config):
    providers = config.get("rule-providers")
    if not isinstance(providers, dict):
        raise ConfigError("source config must contain a rule-providers mapping")

    apple = providers.get("Apple")
    apple_dev = providers.get("AppleDev")
    if isinstance(apple, dict) and isinstance(apple_dev, dict):
        if apple.get("path") and apple.get("path") == apple_dev.get("path"):
            apple["path"] = "./providers/rule/Apple.yaml"


def merge_custom_rules(config, rule_sets):
    providers = config.setdefault("rule-providers", {})
    if not isinstance(providers, dict):
        raise ConfigError("source rule-providers must be a mapping")

    for name in list(providers):
        if name.startswith(CUSTOM_PROVIDER_PREFIX):
            del providers[name]

    for rule_set in rule_sets:
        name = rule_set["name"]
        if name in providers:
            raise ConfigError(f"source config already defines custom provider name: {name}")
        providers[name] = {
            "type": "inline",
            "behavior": "classical",
            "payload": list(rule_set["payload"]),
        }

    source_rules = config.get("rules")
    if not isinstance(source_rules, list):
        raise ConfigError("source config must contain a rules list")
    source_rules = [
        rule
        for rule in source_rules
        if not (
            isinstance(rule, str)
            and rule.startswith("RULE-SET," + CUSTOM_PROVIDER_PREFIX)
        )
    ]
    custom_rules = [
        f"RULE-SET,{rule_set['name']},{rule_set['target']}" for rule_set in rule_sets
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

    expected_prefix = [
        f"RULE-SET,{rule_set['name']},{rule_set['target']}" for rule_set in rule_sets
    ]
    if rules[: len(expected_prefix)] != expected_prefix:
        raise ConfigError("custom rules are not at the beginning in the declared priority order")
    if not rules or not rules[-1].startswith("MATCH,"):
        raise ConfigError("the final source rule must remain MATCH")

    ai_auto = _group_by_name(config, AI_AUTO_GROUP)
    ai_group = _group_by_name(config, AI_GROUP)
    fallback = _group_by_name(config, FALLBACK_GROUP)
    if not ai_auto or ai_auto.get("exclude-filter") != AI_EXCLUDE_FILTER:
        raise ConfigError(f"{AI_AUTO_GROUP} is missing its exclusion filter")
    if not ai_group or ai_group.get("default-selected") != AI_AUTO_GROUP:
        raise ConfigError(f"{AI_GROUP} must default to {AI_AUTO_GROUP}")
    if not fallback or fallback.get("default-selected") != "DIRECT":
        raise ConfigError(f"{FALLBACK_GROUP} must default to DIRECT")


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


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Merge maintainable custom rules into a FlClash/Mihomo subscription."
    )
    parser.add_argument(
        "source",
        nargs="?",
        help=f"subscription YAML (default: {DEFAULT_SOURCE})",
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
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    try:
        rule_sets = load_rule_sets()
        rule_count = sum(len(rule_set["payload"]) for rule_set in rule_sets)
        if args.check_rules:
            print(f"Rule validation passed: {len(rule_sets)} sets, {rule_count} rules")
            return 0

        source_path = Path(args.source).resolve() if args.source else DEFAULT_SOURCE
        if not source_path.is_file():
            raise ConfigError(
                f"subscription not found: {source_path}\n"
                f"Place the current subscription at {DEFAULT_SOURCE} or pass a path."
            )

        source_config = load_yaml(source_path)
        merged = apply_customizations(source_config, rule_sets)
        if args.check:
            print(
                f"Configuration validation passed: {source_path} "
                f"({len(rule_sets)} custom sets, {rule_count} rules)"
            )
            return 0

        output_path = DEFAULT_OUTPUT_DIR / f"{OUTPUT_PREFIX}{source_path.name}"
        write_yaml_atomic(output_path, merged)
        print(f"Merged configuration saved to: {output_path}")
        return 0
    except (ConfigError, OSError, yaml.YAMLError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
