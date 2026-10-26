const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const scriptPath = path.join(__dirname, "..", "dist", "override.js");

function loadMain(errors = []) {
  const source = fs.readFileSync(scriptPath, "utf8");
  const context = {
    console: { error: (message) => errors.push(String(message)) },
  };
  vm.createContext(context);
  vm.runInContext(
    `${source}\nglobalThis.__extensionMain = main;\nglobalThis.__customRules = CUSTOM_RULES;`,
    context,
  );
  return { main: context.__extensionMain, customRules: context.__customRules };
}

function loadMainWithoutConsole() {
  const source = fs.readFileSync(scriptPath, "utf8");
  const context = { console: undefined };
  vm.createContext(context);
  vm.runInContext(`${source}\nglobalThis.__extensionMain = main;`, context);
  return context.__extensionMain;
}

// Airport #1 naming: emoji + 中文, plus bounded ascii.
const US_NODES = [
  "🇺🇸 美国-01",
  "🇺🇸 美国-BGP-05【优化】",
  "🇺🇸 Basic-美国-BGP-01|v202605",
  "US-01",
];
const INFO_NODES = [
  "Expire: 2027-08-18",
  "Traffic: 316.97GB | 1.66TB",
  "Sync: 2026-10-15 20:42:00",
  "🇺🇳 官网 example.invalid|v1",
];

function sampleConfig() {
  const proxies = [
    { name: US_NODES[0], type: "ss", server: "us.example", port: 443 },
    { name: US_NODES[1], type: "ss", server: "us-bgp.example", port: 443 },
    { name: US_NODES[2], type: "ss", server: "us-basic.example", port: 443 },
    { name: US_NODES[3], type: "ss", server: "us-ascii.example", port: 443 },
    { name: "🇩🇪 德国-01", type: "ss", server: "de.example", port: 443 },
    { name: "🇭🇰 香港-01", type: "ss", server: "hk.example", port: 443 },
    { name: "🇹🇼 台湾-01", type: "ss", server: "tw.example", port: 443 },
    { name: "Russia-Moscow-01", type: "ss", server: "ru.example", port: 443 },
    { name: "Australia-Sydney-01", type: "ss", server: "au.example", port: 443 },
    ...INFO_NODES.map((name, index) => ({
      name,
      type: "ss",
      server: `info-${index}.example`,
      port: 443,
    })),
  ];
  const names = proxies.map((proxy) => proxy.name);
  return {
    proxies,
    "proxy-groups": [
      { name: "手动选择", type: "select", proxies: ["自动选择", ...names] },
      { name: "Ai自动选择", type: "url-test", proxies: names },
      { name: "Ai+", type: "select", proxies: ["手动选择", ...names] },
      { name: "漏网之鱼", type: "select", proxies: ["手动选择", "DIRECT"] },
      { name: "自动选择", type: "url-test", proxies: names },
      { name: "Google", type: "select", proxies: ["自动选择"] },
    ],
    "rule-providers": {
      Apple: { path: "./providers/rule/AppleDev.yaml" },
      AppleDev: { path: "./providers/rule/AppleDev.yaml" },
    },
    rules: [
      "DOMAIN-SUFFIX,science.org,DIRECT",
      // Exact duplicate of a custom rule: must be deduplicated, not repeated.
      "DOMAIN-SUFFIX,doubleclick.net,REJECT",
      "RULE-SET,Custom-Academic,DIRECT",
      "RULE-SET,Google,Google",
      "MATCH,漏网之鱼",
    ],
  };
}

// Airport #2 (nanoPort-style): 狮城/天妇罗/碳仔雞 names, "| protocol" suffixes,
// four different info lines, and no Ai+ group at all.
const NANO_US_NODES = [
  "🇺🇸 狮城沙嗲串 | IPv4",
  "🇺🇸 美国龙虾卷 | DDNSv4",
  "🇺🇸 美国奶油派 | CT IP",
  "🇺🇸 美国汉堡包 | CT CU",
  "🇺🇸 美国苹果派 | CM",
];
const NANO_OTHER_NODES = [
  "🇸🇬 狮城肉骨茶 | IPv4",
  "🇯🇵 日本天妇罗 | DDNSv4",
  "🇭🇰 香港碳仔雞 | IPv4",
];
const NANO_INFO_NODES = [
  "剩余流量: 876.18 GB",
  "距离下次重置剩余：24 天",
  "套餐到期：2027-10-08",
  // Airport hostnames are anonymised: the filter only needs the shape.
  "官网 example.invalid example2.invalid 群组 t.me/example",
];

function nanoportConfig() {
  const names = [...NANO_US_NODES, ...NANO_OTHER_NODES, ...NANO_INFO_NODES];
  const proxies = names.map((name, index) => ({
    name,
    type: "vless",
    server: `n${index}.example`,
    port: 443,
  }));
  return {
    proxies,
    "proxy-groups": [
      { name: "自动选择", type: "url-test", proxies: names },
      { name: "战略转移", type: "url-test", proxies: names },
      { name: "漏网之鱼", type: "select", proxies: ["自动选择", "DIRECT"] },
    ],
    "rule-providers": {},
    rules: ["DOMAIN-SUFFIX,bilibili.com,DIRECT", "MATCH,漏网之鱼"],
  };
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function byName(result, name) {
  return result["proxy-groups"].find((group) => group.name === name);
}

// Every injected rule must point at a target this config really defines,
// otherwise mihomo refuses to load the whole subscription. Group member lists
// are checked too: a member that is neither a group, a proxy nor a builtin is
// just as fatal.
function assertNoDanglingTargets(result) {
  const groups = (result["proxy-groups"] || []).filter(Boolean);
  const available = new Set([
    ...groups.map((group) => group.name).filter(Boolean),
    ...((result.proxies || []).map((proxy) => proxy && proxy.name).filter(Boolean)),
    "DIRECT",
    "REJECT",
    "REJECT-DROP",
    "PASS",
    "COMPATIBLE",
  ]);
  for (const group of groups) {
    for (const member of group.proxies || []) {
      assert.ok(available.has(member), `group ${group.name} has dangling member ${member}`);
    }
    for (const provider of group.use || []) {
      assert.ok(
        (result["proxy-providers"] || {})[provider],
        `group ${group.name} uses unknown provider ${provider}`,
      );
    }
  }
  // Only our injected rules: a source subscription may legitimately carry its
  // own pre-existing references, and that is not something this script caused.
  const injected = result.__flclashRules ? result.__flclashRules.rules : 0;
  for (const rule of result.rules.slice(0, injected)) {
    if (rule.startsWith("RULE-SET,") || rule.startsWith("MATCH,")) continue;
    const target = rule.split(",").map((part) => part.trim())[2];
    assert.ok(!target || available.has(target), `dangling target ${target} in ${rule}`);
  }
}

// The whole config must be loadable: group members AND every rule target,
// including the subscription's own rules.
function assertFullyLoadable(result) {
  const groups = (result["proxy-groups"] || []).filter(Boolean);
  const available = new Set([
    ...groups.map((group) => group.name).filter(Boolean),
    ...((result.proxies || []).map((proxy) => proxy && proxy.name).filter(Boolean)),
    "DIRECT",
    "REJECT",
    "REJECT-DROP",
    "PASS",
    "COMPATIBLE",
  ]);
  for (const group of groups) {
    for (const member of group.proxies || []) {
      assert.ok(available.has(member), `group ${group.name} has dangling member ${member}`);
    }
  }
  for (const rule of result.rules) {
    if (rule.startsWith("RULE-SET,")) continue;
    const parts = rule.split(",").map((part) => part.trim());
    const target = parts[0] === "MATCH" ? parts[1] : parts[2];
    assert.ok(!target || available.has(target), `rule ${rule} -> dangling ${target}`);
  }
}

test("inline subscription builds the US-whitelist groups and a marker", () => {
  const { main, customRules } = loadMain();
  const config = sampleConfig();
  const originalAuto = plain(byName(config, "自动选择"));
  const result = main(config);

  assert.notStrictEqual(result, config);
  assert.equal(byName(result, "Ai自动选择"), undefined);

  // AI_INCLUDE hits both naming styles plus bounded ascii; Germany/HK/TW/
  // Russia/Australia and every info line stay out of the AI pool.
  assert.deepEqual(plain(byName(result, "Ai稳定选择").proxies), US_NODES);
  assert.deepEqual(plain(byName(result, "Ai测速备用").proxies), US_NODES);
  for (const name of INFO_NODES) {
    assert.ok(!byName(result, "Ai稳定选择").proxies.includes(name));
  }
  assert.equal(byName(result, "Ai测速备用").url, "https://chatgpt.com/cdn-cgi/trace");
  assert.equal(byName(result, "Ai测速备用")["expected-status"], 200);
  assert.deepEqual(plain(byName(result, "Ai+").proxies), ["Ai稳定选择", "Ai测速备用"]);
  assert.deepEqual(plain(byName(result, "学术搜索").proxies), [
    "Ai稳定选择",
    "Ai测速备用",
  ]);
  assert.deepEqual(plain(byName(result, "学术访问").proxies), ["DIRECT", "Ai+"]);
  assert.equal(byName(result, "漏网之鱼").proxies[0], "DIRECT");
  assert.deepEqual(plain(byName(result, "自动选择")), originalAuto);
  assert.equal(result["rule-providers"].Apple.path, "./providers/rule/Apple.yaml");

  // Claude fix.
  for (const domain of ["claude.ai", "claude.com", "anthropic.com", "claudeusercontent.com"]) {
    assert.ok(result.rules.includes(`DOMAIN-SUFFIX,${domain},Ai+`), domain);
  }
  // Google unification + dev traffic on the client.
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,google.com,Ai+"));
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,github.com,Ai+"));
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,githubcopilot.com,Ai+"));
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,huggingface.co,Ai+"));
  // High-priority direct exceptions.
  assert.ok(
    result.rules.includes("DOMAIN,sea-ad-single-cell-profiling.s3.amazonaws.com,DIRECT"),
  );
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,ncbi.nlm.nih.gov,DIRECT"));
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,science.org,学术访问"));
  assert.ok(!result.rules.includes("DOMAIN-SUFFIX,science.org,DIRECT"));
  assert.ok(!result.rules.includes("RULE-SET,Custom-Academic,DIRECT"));
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,adobedtm.com,DIRECT"));
  assert.equal(result.rules.at(-1), "MATCH,漏网之鱼");

  // Priority order at the head of the list, and same-key subscription rules
  // are deduplicated.
  assert.deepEqual(result.rules.slice(0, customRules.length), customRules);
  assert.equal(
    result.rules.indexOf("DOMAIN-SUFFIX,doubleclick.net,REJECT"),
    result.rules.lastIndexOf("DOMAIN-SUFFIX,doubleclick.net,REJECT"),
  );
  assertNoDanglingTargets(result);
  assertFullyLoadable(result);

  const marker = plain(result.__flclashRules);
  assert.equal(marker.applied, true);
  assert.equal(marker.mode, "inline");
  assert.equal(marker.rules, customRules.length);
  assert.deepEqual(marker.warnings, []);
  assert.match(marker.version, /^\d+\.\d+\.\d+$/);
});

test("default desktop marker survives JSON serialization and exposes the 1.4.1 boundary", () => {
  const { main } = loadMain();
  const original = sampleConfig();
  const result = JSON.parse(JSON.stringify(main(original)));
  assert.equal(result.__flclashRules.applied, true);
  assert.equal(result.__flclashRules.version, "1.1.1");
  assert.equal(original.__flclashRules, undefined);
  // mihomo-userctl v1.4.1 controller_policy.py POLICY_KEYS. A local contract
  // regression, not a claim of executing that CLI or its core validator.
  const allowed = new Set(["proxy-groups", "rules", "rule-providers"]);
  const rejected = [...new Set([...Object.keys(original), ...Object.keys(result)])]
    .filter(key => !allowed.has(key) &&
      JSON.stringify(original[key]) !== JSON.stringify(result[key]));
  assert.deepEqual(rejected, ["__flclashRules"]);
});

test("extension is idempotent", () => {
  const { main } = loadMain();
  const once = main(sampleConfig());
  const twice = main(once);
  assert.deepEqual(plain(twice), plain(once));
});

test("a different airport without Ai+ gets the group created", () => {
  const errors = [];
  const { main, customRules } = loadMain(errors);
  const result = main(nanoportConfig());
  assert.deepEqual(errors, []);

  // Ai+ did not exist and was created, placed before 漏网之鱼.
  const names = plain(result["proxy-groups"].map((group) => group.name));
  assert.ok(names.includes("Ai+"));
  assert.ok(names.indexOf("Ai+") < names.indexOf("漏网之鱼"));
  assert.equal(byName(result, "Ai+").type, "select");
  assert.deepEqual(plain(byName(result, "Ai+").proxies), [
    "Ai稳定选择",
    "Ai测速备用",
  ]);

  // US nodes of this naming style are found; SG/JP/HK and the four info lines
  // (剩余流量 / 距离下次重置剩余 / 套餐到期 / 官网 …) are not.
  assert.deepEqual(plain(byName(result, "Ai稳定选择").proxies), NANO_US_NODES);
  for (const name of [...NANO_OTHER_NODES, ...NANO_INFO_NODES]) {
    assert.ok(!byName(result, "Ai稳定选择").proxies.includes(name), name);
  }

  // Existing groups of the new airport are untouched.
  assert.ok(byName(result, "自动选择"));
  assert.ok(byName(result, "战略转移"));
  assert.equal(byName(result, "漏网之鱼").proxies[0], "DIRECT");
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,bilibili.com,DIRECT"));

  // All AI rules survive because Ai+ now exists.
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,claude.ai,Ai+"));
  assert.ok(result.rules.includes("DOMAIN,scholar.google.com,学术搜索"));
  assert.deepEqual(result.rules.slice(0, customRules.length), customRules);
  assertNoDanglingTargets(result);
  assertFullyLoadable(result);

  const marker = plain(result.__flclashRules);
  assert.equal(marker.applied, true);
  assert.ok(marker.warnings.some((warning) => warning.includes("Ai+")));
});

test("proxy-providers subscription resolves US nodes at runtime", () => {
  const config = {
    "proxy-providers": {
      sub: { type: "http", url: "https://example.test/sub", path: "./p.yaml" },
    },
    "proxy-groups": [
      { name: "自动选择", type: "url-test", use: ["sub"] },
      { name: "Ai+", type: "select", proxies: ["手动选择"] },
      { name: "手动选择", type: "select", proxies: ["自动选择"] },
      { name: "漏网之鱼", type: "select", proxies: ["手动选择", "DIRECT"] },
    ],
    rules: ["MATCH,漏网之鱼"],
  };
  const errors = [];
  const { main, customRules } = loadMain(errors);
  const result = main(config);
  assert.deepEqual(errors, []);

  const includeFilter =
    "(?i)(?:🇺🇸|美国|美國|america|united[ -]?states|u\\.s\\.a\\.?|(?:^|[^a-z])(?:us|usa)(?:[^a-z]|$))";
  // Same three-group shape as inline mode, just resolved by the core.
  const stable = byName(result, "Ai稳定选择");
  const auto = byName(result, "Ai测速备用");
  assert.deepEqual(plain(stable.use), ["sub"]);
  assert.deepEqual(plain(auto.use), ["sub"]);
  assert.equal(stable.filter, includeFilter);
  assert.equal(auto.filter, includeFilter);
  assert.ok(stable["exclude-filter"].includes("expire"));
  assert.equal(auto.url, "https://chatgpt.com/cdn-cgi/trace");
  assert.deepEqual(plain(byName(result, "Ai+").proxies), ["Ai稳定选择", "Ai测速备用"]);
  assert.deepEqual(plain(byName(result, "学术搜索").proxies), [
    "Ai稳定选择",
    "Ai测速备用",
  ]);
  assert.deepEqual(plain(byName(result, "学术访问").proxies), ["DIRECT", "Ai+"]);
  assert.equal(byName(result, "漏网之鱼").proxies[0], "DIRECT");
  assert.deepEqual(result.rules.slice(0, customRules.length), customRules);
  assertNoDanglingTargets(result);
  assertFullyLoadable(result);
  assert.equal(result.__flclashRules.mode, "provider");
});

test("no usable node source keeps the config loadable and skips AI rules", () => {
  const config = {
    // A new airport with no US-named node and no provider to resolve.
    proxies: [
      { name: "🇯🇵 日本-01", type: "ss", server: "jp.example", port: 443 },
      { name: "剩余流量: 10 GB", type: "ss", server: "info.example", port: 443 },
    ],
    "proxy-groups": [
      { name: "自动选择", type: "url-test", proxies: ["🇯🇵 日本-01"] },
      { name: "漏网之鱼", type: "select", proxies: ["自动选择", "DIRECT"] },
    ],
    "rule-providers": {},
    rules: ["MATCH,漏网之鱼"],
  };
  const errors = [];
  const { main, customRules } = loadMain(errors);
  const result = main(config);
  assert.deepEqual(errors, []);

  // No AI groups were created and no Ai+-targeting rule was injected, so the
  // subscription still loads.
  assert.equal(byName(result, "Ai+"), undefined);
  assert.equal(byName(result, "Ai稳定选择"), undefined);
  assert.ok(!result.rules.some((rule) => rule.includes(",Ai+")));
  assert.ok(!result.rules.some((rule) => rule.includes(",学术搜索")));
  assert.ok(!result.rules.some((rule) => rule.includes(",学术访问")));
  // Direct/ad-block/tailscale rules still apply.
  assert.equal(result.rules[0], "DOMAIN-SUFFIX,doubleclick.net,REJECT");
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,tailscale.io,DIRECT"));
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,adobedtm.com,DIRECT"));
  assert.equal(result.rules.at(-1), "MATCH,漏网之鱼");
  assertNoDanglingTargets(result);

  const marker = plain(result.__flclashRules);
  assert.equal(marker.applied, true);
  assert.equal(marker.mode, "no-nodes");
  const expectedRules = customRules.filter(rule =>
    ["DIRECT", "REJECT"].includes(rule.split(",")[2]));
  assert.equal(marker.rules, expectedRules.length);
  assert.deepEqual(plain(result.rules.slice(0, marker.rules)), plain(expectedRules));
  assert.ok(marker.warnings.some((warning) => warning.includes("no usable AI node source")));
});

test("a subscription without proxy-groups degrades without breaking", () => {
  const { main } = loadMain();
  const config = { rules: ["MATCH,漏网之鱼"] };
  const result = loadMain().main(config);

  assert.equal(result.__flclashRules.mode, "degraded");
  assertNoDanglingTargets(result);
  // Only DIRECT/REJECT rules can survive when no group exists at all.
  for (const rule of result.rules) {
    const parts = rule.split(",").map((part) => part.trim());
    if (parts[0] === "MATCH") continue;
    assert.ok(
      parts[parts.length - 1] === "no-resolve"
        ? parts[parts.length - 2] === "DIRECT"
        : parts[parts.length - 1] === "DIRECT" || parts[parts.length - 1] === "REJECT",
      `unexpected retained rule: ${rule}`,
    );
  }
  assert.equal(result.rules.at(-1), "MATCH,漏网之鱼");
});

test("missing fallback group only skips the fallback adjustment", () => {
  const errors = [];
  const config = sampleConfig();
  // A real airport that renamed the fallback group keeps pointing its MATCH
  // rule at that renamed group, so the fixture does the same.
  config["proxy-groups"] = config["proxy-groups"].filter(
    (group) => group.name !== "漏网之鱼",
  );
  config["proxy-groups"].push({ name: "兜底", type: "select", proxies: ["自动选择"] });
  config.rules = config.rules.map((rule) =>
    rule === "MATCH,漏网之鱼" ? "MATCH,兜底" : rule,
  );
  const result = loadMain(errors).main(config);

  assert.equal(result.__flclashRules.applied, true);
  assert.equal(result.__flclashRules.mode, "inline");
  assert.ok(
    result.__flclashRules.warnings.some((warning) => warning.includes("漏网之鱼")),
  );
  assert.deepEqual(plain(byName(result, "Ai稳定选择").proxies), US_NODES);
  assert.equal(result.rules.at(-1), "MATCH,兜底");
  assertFullyLoadable(result);
});

test("a referenced legacy group is never deleted", () => {
  // Regression: Ai自动选择 used to be dropped unconditionally. A subscription
  // whose other groups or rules still point at it would end up with a dangling
  // target and mihomo would refuse the whole config.
  const config = sampleConfig();
  config["proxy-groups"].push({
    name: "AI专用",
    type: "select",
    proxies: ["Ai自动选择"],
  });
  config.rules.push("DOMAIN,example.org,Ai自动选择");

  const result = loadMain().main(config);
  assert.ok(byName(result, "Ai自动选择"), "referenced legacy group must survive");
  assert.deepEqual(plain(byName(result, "AI专用").proxies), ["Ai自动选择"]);
  assert.ok(result.rules.includes("DOMAIN,example.org,Ai自动选择"));
  assertFullyLoadable(result);
});

test("an unreferenced legacy group is still cleaned up", () => {
  const result = loadMain().main(sampleConfig());
  assert.equal(byName(result, "Ai自动选择"), undefined);
});

test("a provider-backed Ai+ does not leak unfiltered nodes", () => {
  // Ai+ arriving with use+filter from the subscription: after the override it
  // must hold only the two generated groups, otherwise mihomo merges the
  // provider's non-US and informational nodes straight into Ai+.
  const config = {
    "proxy-providers": { sub: { type: "http", url: "https://example.test/sub" } },
    "proxy-groups": [
      {
        name: "Ai+",
        type: "select",
        use: ["sub"],
        filter: "(?i)hk",
        "exclude-filter": "(?i)expire",
        "include-all": true,
      },
      { name: "漏网之鱼", type: "select", proxies: ["DIRECT"] },
    ],
    rules: ["MATCH,漏网之鱼"],
  };
  const result = loadMain().main(config);
  const ai = byName(result, "Ai+");
  assert.deepEqual(plain(ai.proxies), ["Ai稳定选择", "Ai测速备用"]);
  for (const key of ["use", "filter", "exclude-filter", "include-all"]) {
    assert.ok(!(key in ai), `Ai+ must not keep ${key}`);
  }
  assertFullyLoadable(result);
});

test("invalid subscription returns the original config with a full stack", () => {
  const errors = [];
  const config = sampleConfig();
  // Duplicate group names: unrecoverable, so the whole override is refused.
  config["proxy-groups"].push({ name: "自动选择", type: "select", proxies: [] });
  const snapshot = plain(config);
  const result = loadMain(errors).main(config);

  assert.strictEqual(result, config);
  assert.deepEqual(plain(result), snapshot);
  assert.match(errors[0], /extension skipped/);
  assert.match(errors[0], /at /);
});

test("fail-safe return does not depend on a console implementation", () => {
  const config = sampleConfig();
  config["proxy-groups"].push({ name: "自动选择", type: "select", proxies: [] });
  assert.strictEqual(loadMainWithoutConsole()(config), config);
  assert.strictEqual(loadMainWithoutConsole()(null), null);
});

test("generated extension has no runtime fetch or unapproved URLs", () => {
  const source = fs.readFileSync(scriptPath, "utf8");
  assert.doesNotMatch(source, /\b(fetch|require|importScripts|XMLHttpRequest)\s*\(/);
  const approvedHealthUrls = [
    "https://chatgpt.com/cdn-cgi/trace",
    "https://www.gstatic.com/generate_204",
  ];
  let remaining = source;
  for (const url of approvedHealthUrls) {
    assert.ok(remaining.includes(url), url);
    remaining = remaining.split(url).join("");
  }
  assert.doesNotMatch(remaining, /https:\/\//);
});
