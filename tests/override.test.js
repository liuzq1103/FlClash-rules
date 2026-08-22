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
  vm.runInContext(`${source}\nglobalThis.__extensionMain = main;`, context);
  return context.__extensionMain;
}

function loadMainWithoutConsole() {
  const source = fs.readFileSync(scriptPath, "utf8");
  const context = { console: undefined };
  vm.createContext(context);
  vm.runInContext(`${source}\nglobalThis.__extensionMain = main;`, context);
  return context.__extensionMain;
}

function sampleConfig() {
  const proxies = [
    { name: "🇺🇸 美国-01", type: "ss", server: "us.example", port: 443 },
    { name: "🇩🇪 德国-01", type: "ss", server: "de.example", port: 443 },
    { name: "🇭🇰 香港-01", type: "ss", server: "hk.example", port: 443 },
    { name: "🇲🇴 澳门-01", type: "ss", server: "mo.example", port: 443 },
    { name: "🇹🇼 台湾-01", type: "ss", server: "tw.example", port: 443 },
    { name: "剩余流量：1 TB", type: "ss", server: "info.example", port: 443 },
  ];
  const names = proxies.map((proxy) => proxy.name);
  return {
    proxies,
    "proxy-groups": [
      { name: "手动选择", type: "select", proxies: ["自动选择", ...names] },
      { name: "Ai+", type: "select", proxies: ["手动选择", ...names] },
      { name: "漏网之鱼", type: "select", proxies: ["手动选择", "DIRECT"] },
      { name: "自动选择", type: "url-test", proxies: names },
      { name: "Google", type: "select", proxies: ["自动选择"] },
    ],
    "rule-providers": {
      Apple: { path: "./providers/rule/AppleDev.yaml" },
      AppleDev: { path: "./providers/rule/AppleDev.yaml" },
    },
    rules: ["RULE-SET,Google,Google", "MATCH,漏网之鱼"],
  };
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test("extension creates safe dynamic groups and preserves global auto group", () => {
  const config = sampleConfig();
  const originalAuto = plain(config["proxy-groups"].find((group) => group.name === "自动选择"));
  const result = loadMain()(config);

  assert.notStrictEqual(result, config);
  const byName = (name) => result["proxy-groups"].find((group) => group.name === name);
  assert.deepEqual(plain(byName("Ai自动选择").proxies), ["🇺🇸 美国-01", "🇩🇪 德国-01"]);
  assert.deepEqual(plain(byName("Ai+").proxies), [
    "Ai自动选择",
    "🇺🇸 美国-01",
    "🇩🇪 德国-01",
  ]);
  assert.deepEqual(plain(byName("学术搜索").proxies), [
    "Ai自动选择",
    "🇺🇸 美国-01",
    "🇩🇪 德国-01",
  ]);
  assert.equal(byName("漏网之鱼").proxies[0], "DIRECT");
  assert.deepEqual(plain(byName("自动选择")), originalAuto);
  assert.equal(result["rule-providers"].Apple.path, "./providers/rule/Apple.yaml");
  assert.equal(result.rules[0], "DOMAIN-SUFFIX,doubleclick.net,REJECT");
  assert.ok(result.rules.includes("DOMAIN,scholar.google.com,学术搜索"));
  assert.equal(result.rules.at(-1), "MATCH,漏网之鱼");
});

test("extension is idempotent", () => {
  const main = loadMain();
  const once = main(sampleConfig());
  const twice = main(once);
  assert.deepEqual(plain(twice), plain(once));
});

test("extension returns the untouched original config on incompatibility", () => {
  const errors = [];
  const config = sampleConfig();
  config["proxy-groups"] = config["proxy-groups"].filter((group) => group.name !== "Ai+");
  const snapshot = plain(config);
  const result = loadMain(errors)(config);

  assert.strictEqual(result, config);
  assert.deepEqual(plain(result), snapshot);
  assert.match(errors[0], /extension skipped/);
});

test("fail-safe return does not depend on a console implementation", () => {
  const config = sampleConfig();
  config["proxy-groups"] = [];
  assert.strictEqual(loadMainWithoutConsole()(config), config);
});

test("generated extension has no network or module dependencies", () => {
  const source = fs.readFileSync(scriptPath, "utf8");
  assert.doesNotMatch(source, /\b(fetch|require|importScripts|XMLHttpRequest)\s*\(/);
  assert.doesNotMatch(source, /https:\/\//);
});
