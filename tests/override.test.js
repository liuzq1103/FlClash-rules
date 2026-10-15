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

// Both observed airport naming styles for US nodes, plus non-US regions and
// the four informational node lines real subscriptions inject.
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
  "🇺🇳 官网 helloshudong.com|v202605",
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

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test("inline subscription builds US-whitelist groups and applies the marker", () => {
  const { main, customRules } = loadMain();
  const config = sampleConfig();
  const originalAuto = plain(config["proxy-groups"].find((group) => group.name === "自动选择"));
  const result = main(config);

  assert.notStrictEqual(result, config);
  const byName = (name) => result["proxy-groups"].find((group) => group.name === name);
  assert.equal(byName("Ai自动选择"), undefined);

  // AI_INCLUDE hits both US naming styles plus the bounded ASCII style;
  // Germany/HK/TW/Russia/Australia and all four info lines are kept out.
  assert.deepEqual(plain(byName("Ai稳定选择").proxies), US_NODES);
  assert.deepEqual(plain(byName("Ai测速备用").proxies), US_NODES);
  for (const name of INFO_NODES) {
    assert.ok(!byName("Ai稳定选择").proxies.includes(name));
  }
  assert.equal(byName("Ai测速备用").url, "https://chatgpt.com/cdn-cgi/trace");
  assert.equal(byName("Ai测速备用")["expected-status"], 200);
  assert.deepEqual(plain(byName("Ai+").proxies), ["Ai稳定选择", "Ai测速备用"]);
  assert.deepEqual(plain(byName("学术搜索").proxies), ["Ai稳定选择", "Ai测速备用"]);
  assert.deepEqual(plain(byName("学术访问").proxies), ["DIRECT", "Ai+"]);
  assert.equal(byName("漏网之鱼").proxies[0], "DIRECT");
  assert.deepEqual(plain(byName("自动选择")), originalAuto);
  assert.equal(result["rule-providers"].Apple.path, "./providers/rule/Apple.yaml");

  // Claude fix: claude.ai and friends must be present.
  for (const domain of ["claude.ai", "claude.com", "anthropic.com", "claudeusercontent.com"]) {
    assert.ok(result.rules.includes(`DOMAIN-SUFFIX,${domain},Ai+`), domain);
  }
  // Copilot moved to DIRECT; noise rules removed.
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,githubcopilot.com,DIRECT"));
  for (const gone of [
    "DOMAIN,default.exp-tas.com,Ai+",
    "DOMAIN-SUFFIX,intercom.io,Ai+",
    "DOMAIN-SUFFIX,roboflow.com,Ai+",
    "DOMAIN-SUFFIX,generativelanguage.googleapis.com,Ai+",
  ]) {
    assert.ok(!result.rules.includes(gone), gone);
  }
  assert.ok(result.rules.includes("DOMAIN,scholar.google.com,学术搜索"));
  assert.ok(result.rules.includes("DOMAIN,google.com,Ai+"));
  assert.ok(result.rules.includes("DOMAIN-SUFFIX,science.org,学术访问"));
  assert.ok(!result.rules.includes("DOMAIN-SUFFIX,science.org,DIRECT"));
  assert.ok(!result.rules.includes("RULE-SET,Custom-Academic,DIRECT"));
  assert.equal(result.rules.at(-1), "MATCH,漏网之鱼");

  // Custom rules keep their declared priority order at the head of the list,
  // and subscription rules with the same match key are deduplicated.
  assert.deepEqual(result.rules.slice(0, customRules.length), customRules);
  assert.equal(
    result.rules.indexOf("DOMAIN-SUFFIX,doubleclick.net,REJECT"),
    result.rules.lastIndexOf("DOMAIN-SUFFIX,doubleclick.net,REJECT"),
  );

  // Visible application marker for inline mode.
  assert.deepEqual(plain(result.__flclashRules), {
    applied: true,
    version: result.__flclashRules.version,
    mode: "inline",
    warnings: [],
  });
  assert.match(result.__flclashRules.version, /^\d+\.\d+\.\d+$/);
});

test("extension is idempotent", () => {
  const { main } = loadMain();
  const once = main(sampleConfig());
  const twice = main(once);
  assert.deepEqual(plain(twice), plain(once));
});

test("proxy-providers subscription keeps Ai+ with a runtime filter", () => {
  const { main, customRules } = loadMain();
  const config = {
    "proxy-providers": {
      sub: { type: "http", url: "https://example.test/sub", path: "./p.yaml" },
    },
    "proxy-groups": [
      { name: "Ai自动选择", type: "url-test", use: ["sub"] },
      { name: "Ai+", type: "select", proxies: ["手动选择"] },
      { name: "手动选择", type: "select", proxies: ["自动选择"] },
      { name: "漏网之鱼", type: "select", proxies: ["手动选择", "DIRECT"] },
    ],
    rules: ["MATCH,漏网之鱼"],
  };
  const errors = [];
  const result = main(config);
  assert.deepEqual(errors, []);

  const byName = (name) => result["proxy-groups"].find((group) => group.name === name);
  const ai = byName("Ai+");
  assert.ok(ai, "Ai+ must survive on provider subscriptions");
  assert.deepEqual(plain(ai.use), ["sub"]);
  assert.equal(
    ai.filter,
    "(?i)(?:🇺🇸|美国|美國|united[ -]?states|(?:^|[^a-z])(?:us|usa)(?:[^a-z]|$))",
  );
  assert.ok(ai["exclude-filter"].includes("expire"));
  // Node groups are not rebuilt when nodes cannot be enumerated.
  assert.equal(byName("Ai稳定选择"), undefined);
  assert.equal(byName("Ai测速备用"), undefined);
  assert.equal(byName("Ai自动选择"), undefined);
  assert.deepEqual(plain(byName("学术搜索").proxies), ["Ai+"]);
  assert.deepEqual(plain(byName("学术访问").proxies), ["DIRECT", "Ai+"]);
  assert.equal(byName("漏网之鱼").proxies[0], "DIRECT");
  assert.deepEqual(result.rules.slice(0, customRules.length), customRules);
  assert.equal(result.rules.at(-1), "MATCH,漏网之鱼");
  assert.equal(result.__flclashRules.mode, "provider");
  assert.equal(result.__flclashRules.applied, true);
  assert.deepEqual(plain(result.__flclashRules.warnings), []);
});

test("missing Ai+ group still overrides rules and leaves a visible marker", () => {
  const errors = [];
  const config = sampleConfig();
  config["proxy-groups"] = config["proxy-groups"].filter((group) => group.name !== "Ai+");
  const snapshot = plain(config);
  const result = loadMain(errors).main(config);

  // Degraded, not failed: rules are applied and the marker says so.
  assert.notStrictEqual(result, config);
  assert.equal(result.__flclashRules.applied, true);
  assert.equal(result.__flclashRules.mode, "degraded");
  assert.ok(result.__flclashRules.warnings.some((warning) => warning.includes("Ai+")));
  assert.equal(result.rules[0], "DOMAIN-SUFFIX,doubleclick.net,REJECT");
  assert.equal(result.rules.at(-1), "MATCH,漏网之鱼");
  // Untouched parts of the subscription stay untouched.
  assert.deepEqual(plain(result.proxies), snapshot.proxies);
  // No group was rewritten in degraded mode.
  assert.deepEqual(
    plain(result["proxy-groups"].map((group) => group.name)),
    snapshot["proxy-groups"].map((group) => group.name),
  );
});

test("missing fallback group only skips the fallback adjustment", () => {
  const errors = [];
  const config = sampleConfig();
  config["proxy-groups"] = config["proxy-groups"].filter((group) => group.name !== "漏网之鱼");
  const result = loadMain(errors).main(config);

  assert.equal(result.__flclashRules.applied, true);
  assert.equal(result.__flclashRules.mode, "inline");
  assert.ok(result.__flclashRules.warnings.some((warning) => warning.includes("漏网之鱼")));
  const byName = (name) => result["proxy-groups"].find((group) => group.name === name);
  assert.deepEqual(plain(byName("Ai稳定选择").proxies), US_NODES);
  assert.equal(result.rules.at(-1), "MATCH,漏网之鱼");
});

test("hard failure returns the original config with a full stack trace", () => {
  const errors = [];
  const config = sampleConfig();
  delete config.proxies; // no inline nodes and no proxy-providers -> throw
  const snapshot = plain(config);
  const result = loadMain(errors).main(config);

  assert.strictEqual(result, config);
  assert.deepEqual(plain(result), snapshot);
  assert.match(errors[0], /extension skipped/);
  assert.match(errors[0], /at /); // the logged error includes the stack
});

test("fail-safe return does not depend on a console implementation", () => {
  const config = sampleConfig();
  delete config.proxies;
  assert.strictEqual(loadMainWithoutConsole()(config), config);
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
