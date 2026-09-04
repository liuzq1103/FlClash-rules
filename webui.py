"""Local web UI for the custom rule workflow.

Serves a single HTML page and a small JSON API on 127.0.0.1 so new sites
can be added to rules/*.yaml and dist/override.js rebuilt from a browser.

Run: python webui.py --port 8765 --no-browser
"""

import argparse
import ipaddress
import json
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import yaml

import clash


BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "static" / "index.html"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# Common two-level public suffixes so registrable_domain("www.pku.edu.cn")
# returns "pku.edu.cn" instead of "edu.cn".
MULTI_PART_SUFFIXES = {
    "ac.cn", "com.cn", "edu.cn", "gov.cn", "net.cn", "org.cn",
    "com.hk", "edu.hk", "gov.hk", "idv.hk", "net.hk", "org.hk",
    "com.tw", "edu.tw", "gov.tw", "idv.tw", "net.tw", "org.tw",
    "com.au", "edu.au", "gov.au", "net.au", "org.au",
    "ac.jp", "co.jp", "go.jp", "ne.jp", "or.jp",
    "ac.uk", "co.uk", "gov.uk", "me.uk", "net.uk", "org.uk",
    "com.br", "gov.br", "net.br", "org.br",
    "com.mx", "net.mx", "org.mx",
    "co.in", "firm.in", "net.in", "org.in",
    "co.kr", "ne.kr", "or.kr",
    "com.sg", "edu.sg", "net.sg", "org.sg",
    "com.tr", "edu.tr", "net.tr", "org.tr",
}

_PAYLOAD_LINE = re.compile(r"^\s*-\s+\S")
_WRITE_LOCK = threading.Lock()


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def extract_host(text):
    """Return the normalized host name of a pasted URL or bare domain."""
    if not isinstance(text, str):
        return None
    tokens = text.strip().split()
    if not tokens:
        return None
    candidate = tokens[0]
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        host = urlsplit(candidate).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.strip(".").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def registrable_domain(host):
    """Return the registrable domain (e.g. "nature.com") of a host name."""
    labels = host.split(".")
    if len(labels) < 3:
        return host if "." in host else None
    last_two = ".".join(labels[-2:])
    if last_two in MULTI_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return last_two


def build_candidates(text):
    """Turn pasted text into candidate routing rules (task 1)."""
    host = extract_host(text)
    if not host:
        raise clash.ConfigError("无法从输入中识别出域名，请粘贴完整网址或裸域名")
    if _is_ip(host):
        rule_type = "IP-CIDR6" if ":" in host else "IP-CIDR"
        return host, [{"rule": f"{rule_type},{host}", "note": f"精确 IP 地址 {host}"}]
    domain = registrable_domain(host) or host
    candidates = [
        {"rule": f"DOMAIN-SUFFIX,{domain}", "note": f"匹配 {domain} 及其全部子域（推荐）"},
        {"rule": f"DOMAIN,{host}", "note": f"仅精确匹配 {host}（不含子域）"},
        {"rule": f"DOMAIN-KEYWORD,{domain}", "note": f"域名中包含 {domain} 即命中（最宽泛）"},
    ]
    return host, candidates


def inspect_rule(rule_text, target_file, index_path=clash.RULES_INDEX):
    """Check a candidate rule against the existing rule base (task 2).

    Returns {"status": "ok"} | {"status": "warn", "warning": ...} |
    {"status": "blocked", "message": ...}.
    """
    try:
        parsed = clash._parse_payload_rule(rule_text, "candidate")
    except clash.ConfigError as error:
        return {"status": "blocked", "message": str(error)}
    try:
        rule_sets = clash.load_rule_sets(index_path)
    except (clash.ConfigError, yaml.YAMLError) as error:
        return {"status": "blocked", "message": f"规则库校验失败：{error}"}

    file_order = [rule_set["file"] for rule_set in rule_sets]
    if target_file not in file_order:
        return {"status": "blocked", "message": f"未知的规则文件: {target_file}"}

    new_position = file_order.index(target_file)
    new_target = rule_sets[new_position]["target"]
    new_entry = parsed[:3]

    exact = None
    covered_by = None
    shadows = []
    for position, rule_set in enumerate(rule_sets):
        is_earlier = position <= new_position
        for rule in rule_set["payload"]:
            existing = clash._parse_payload_rule(rule, rule_set["file"])
            if existing[2] == parsed[2]:
                exact = rule_set
                break
            if is_earlier:
                if covered_by is None and clash._rule_shadows(existing, new_entry):
                    covered_by = {
                        "file": rule_set["file"],
                        "rule": existing[2],
                        "target": rule_set["target"],
                    }
            elif clash._rule_shadows(new_entry, existing):
                shadows.append({
                    "file": rule_set["file"],
                    "rule": existing[2],
                    "target": rule_set["target"],
                })
        if exact is not None:
            break

    if exact is not None:
        return {
            "status": "blocked",
            "message": (
                f"规则已存在于 {exact['file']}（目标 {exact['target']}），"
                "重复添加会导致构建失败"
            ),
        }
    if covered_by is not None:
        return {
            "status": "blocked",
            "message": (
                f"将被 {covered_by['file']} 中的 {covered_by['rule']} 覆盖"
                f"（优先级更高，目标 {covered_by['target']}），添加后不会生效"
            ),
        }
    if shadows:
        same_target = [item for item in shadows if item["target"] == new_target]
        if same_target:
            first = same_target[0]
            return {
                "status": "blocked",
                "message": (
                    f"与 {first['file']} 中的 {first['rule']} 目标相同（{new_target}），"
                    "会使后者变为冗余规则，构建将失败"
                ),
            }
        preview = "、".join(
            f"{item['file']} 的 {item['rule']}" for item in shadows[:3]
        )
        more = f" 等 {len(shadows)} 条" if len(shadows) > 3 else ""
        return {
            "status": "warn",
            "warning": f"该规则优先级更高，将改变现有路由：{preview}{more}",
        }
    return {"status": "ok"}


def _ends_with_payload_entry(lines):
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return bool(_PAYLOAD_LINE.match(line))
    return False


def append_rule(rule_text, target_file, index_path=clash.RULES_INDEX):
    """Append a rule to a payload file, keeping comments (task 3).

    The rule base is re-validated afterwards and the file is restored
    byte-for-byte if validation fails.
    """
    parsed = clash._parse_payload_rule(rule_text, "candidate")
    normalized = parsed[2]
    index_path = Path(index_path)
    rule_sets = clash.load_rule_sets(index_path)
    known_files = {rule_set["file"] for rule_set in rule_sets}
    if target_file not in known_files:
        raise clash.ConfigError(f"未知的规则文件: {target_file}")

    rule_path = index_path.parent / target_file
    original = rule_path.read_bytes().decode("utf-8")
    lines = original.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or not _ends_with_payload_entry(lines):
        raise clash.ConfigError(
            f"{target_file}: 文件末尾不是规则条目，无法安全追加，请手动编辑"
        )
    updated = "\n".join(lines) + f"\n  - {normalized}\n"

    with _WRITE_LOCK:
        clash.write_text_atomic(rule_path, updated)
        try:
            reloaded = clash.load_rule_sets(index_path)
            appended = next(
                rule_set for rule_set in reloaded if rule_set["file"] == target_file
            )
            if normalized not in appended["payload"]:
                raise clash.ConfigError("规则未落入 payload 列表")
        except Exception as error:
            clash.write_text_atomic(rule_path, original)
            raise clash.ConfigError(f"追加后规则校验失败，已回滚原文件：{error}")
    return normalized


def collect_state():
    rule_sets = clash.load_rule_sets()
    files = [
        {
            "file": rule_set["file"],
            "name": rule_set["name"],
            "target": rule_set["target"],
            "count": len(rule_set["payload"]),
        }
        for rule_set in rule_sets
    ]
    stale = True
    if clash.DEFAULT_SCRIPT_OUTPUT.is_file():
        try:
            current = clash.render_override_script(rule_sets)
        except clash.ConfigError:
            current = None
        stale = current is None or (
            clash.DEFAULT_SCRIPT_OUTPUT.read_text(encoding="utf-8") != current
        )
    return {
        "files": files,
        "total": sum(item["count"] for item in files),
        "dist": {
            "exists": clash.DEFAULT_SCRIPT_OUTPUT.is_file(),
            "stale": stale,
            "path": str(clash.DEFAULT_SCRIPT_OUTPUT),
        },
    }


def build_extension(output_path=clash.DEFAULT_SCRIPT_OUTPUT):
    """Regenerate the extension script (task 4)."""
    rule_sets = clash.load_rule_sets()
    script = clash.render_override_script(rule_sets)
    output_path = Path(output_path)
    clash.write_text_atomic(output_path, script)
    count = sum(len(rule_set["payload"]) for rule_set in rule_sets)
    return {"count": count, "path": str(output_path)}


class WebUIRequestHandler(BaseHTTPRequestHandler):
    server_version = "FlClashRulesUI/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass  # keep the console quiet; errors surface through the UI

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            body = path.read_bytes()
        except OSError as error:
            self._send_json({"error": f"无法读取 {path}: {error}"}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("请求体为空")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._send_file(INDEX_PATH, "text/html; charset=utf-8")
        elif path == "/api/state":
            try:
                self._send_json(collect_state())
            except (clash.ConfigError, yaml.YAMLError) as error:
                self._send_json({"error": f"规则库校验失败：{error}"})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            data = self._read_json()
        except ValueError as error:
            self._send_json({"error": f"无效的请求体：{error}"}, 400)
            return
        try:
            self._route_post(path, data)
        except (clash.ConfigError, yaml.YAMLError) as error:
            self._send_json({"error": str(error)}, 400)
        except OSError as error:
            self._send_json({"error": f"读写失败：{error}"}, 500)

    def _route_post(self, path, data):
        if path == "/api/parse":
            host, candidates = build_candidates(data.get("url", ""))
            self._send_json({"host": host, "candidates": candidates})
        elif path == "/api/inspect":
            self._send_json(
                inspect_rule(str(data.get("rule", "")), str(data.get("file", "")))
            )
        elif path == "/api/add-rule":
            rule_text = str(data.get("rule", "")).strip()
            target_file = str(data.get("file", "")).strip()
            inspection = inspect_rule(rule_text, target_file)
            if inspection["status"] == "blocked":
                self._send_json({"error": inspection["message"]}, 409)
                return
            normalized = append_rule(rule_text, target_file)
            self._send_json({
                "ok": True,
                "rule": normalized,
                "file": target_file,
                "warning": inspection.get("warning"),
            })
        elif path == "/api/build":
            result = build_extension()
            self._send_json({"ok": True, **result})
        else:
            self._send_json({"error": "not found"}, 404)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="启动 FlClash 分流规则管理界面（仅监听本机）。"
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"监听地址（默认 {DEFAULT_HOST}）"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"监听端口（默认 {DEFAULT_PORT}）",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="启动后不自动打开浏览器"
    )
    args = parser.parse_args(argv)

    try:
        server = ThreadingHTTPServer((args.host, args.port), WebUIRequestHandler)
    except OSError as error:
        print(
            f"Error: 无法监听 {args.host}:{args.port}（{error}），"
            "请用 --port 换一个端口",
            file=sys.stderr,
        )
        return 1

    url = f"http://{args.host}:{args.port}/"
    print(f"FlClash 分流规则管理界面: {url}（按 Ctrl+C 停止）")
    if not args.no_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
