# FlClash 自定义分流规则

本项目把代理订阅当作动态节点源，把自定义规则同时编译成 Clash Verge Rev / FlClash 可用的 **JavaScript 扩展脚本**，以及服务器用户级 Mihomo 可用的**无秘密策略片段**。客户端或服务器 provider 更新后都会基于最新节点工作，仓库不复制、不保存完整订阅配置。

> 主客户端推荐 Clash Verge Rev。FlClash 使用“脚本”覆写模式；不要使用“自定义 → 一键填入”保存整套节点和策略组，后者是静态副本，节点名称变化后容易失效。

> 项目边界：本仓库 `D:\Desktop\技术\FlClash` 只负责规则源与 PC/服务器策略
> 生成物。服务器端用户服务和 Shell 控制器位于独立仓库
> `D:\Desktop\技术\mihomo-userctl`。前者决定 Mihomo 内部如何分流，后者决定
> 某个服务器 Shell/命令是否进入 Mihomo；不要把两个项目的源码或 Git 历史混在一起。

## 工作方式

```text
原始订阅（自动更新节点）
  → 订阅级 dist/override.js
  → 动态 AI/学术策略组 + 个性化规则
  → Mihomo 运行配置

服务器 subscription provider
  → dist/server-policy.yaml
  → Ai+/学术策略组 + 128 条个性化规则 + MATCH,DIRECT
  → liuzq 用户级 Mihomo
```

- 原始订阅继续负责节点、DNS、通用 provider 和基础分流。
- `rules/*.yaml` 是自定义规则的唯一来源。
- `clash.py` 将分类规则展开为普通 Mihomo 规则，并生成 `dist/override.js` 与 `dist/server-policy.yaml`。
- 两个生成物都不联网、不读取 GitHub、不包含订阅地址、Listener 凭据或节点内容。
- 脚本在副本上修改并完成自检，成功后在配置上留下可见标记 `__flclashRules = { applied: true, ... }`；在客户端"预览"里检查该字段即可区分"覆写成功"和"覆写崩溃返回原配置"。
- 覆写不再静默失败或整体放弃：缺少 `Ai+`、`漏网之鱼` 或整个 `proxy-groups` 时只跳过对应组配置并记录 warning，规则仍然覆写；只有既拿不到内联节点也拿不到 `proxy-providers` 时才返回原始配置。
- 同时支持节点内联（`proxies` 数组）和 `proxy-providers` 型订阅：后者无法在脚本阶段枚举节点名，脚本会保留订阅自己的 `Ai+` 组并写入 `use` + 美国 `filter`，由内核在运行时从 provider 拉取美国节点。

## 目录

```text
FlClash/
├── clash.py
├── webui.py
├── requirements.txt
├── rules/
│   ├── index.yml       # 优先级、文件和目标策略
│   ├── reject.yaml     # 广告拦截
│   ├── ai.yaml         # AI、开发服务、学术代理例外
│   ├── scholar.yaml    # Google Scholar 稳定出口
│   ├── academic.yaml   # 已确认需要直连的学术平台
│   ├── tailscale.yaml  # Tailscale 域名与地址段
│   └── direct.yaml     # 其他明确直连
├── templates/
│   └── override.js.tpl
├── static/
│   └── index.html      # 图形界面
├── dist/
│   ├── override.js          # 生成后粘贴到客户端
│   └── server-policy.yaml   # 服务器 Mihomo 无秘密策略片段
├── docs/
│   └── 服务器Mihomo维护说明.md
├── tests/
├── .github/workflows/validate.yml
```

## 首次部署到 Clash Verge Rev

安装依赖并生成脚本：

```powershell
python -m pip install -r requirements.txt
python clash.py --check-rules
python clash.py
python clash.py --check
```

然后：

1. 在 Clash Verge Rev 中保留并更新自己的原始订阅配置。
2. 给这条订阅配置“扩展脚本”，粘贴 `dist/override.js` 的完整内容。
3. 不要把脚本放到“全局扩展脚本”；全局扩展配置也保持为空。
4. 先使用“预览”确认存在 `Ai稳定选择`、`Ai测速备用`、`学术搜索`、`学术访问`，规则仍以原订阅的 `MATCH` 结束，且配置上有 `__flclashRules: { applied: true }` 标记。
5. 启用订阅后，在 `Ai稳定选择` 中固定一个可正常打开 ChatGPT 的美国节点；`Ai+` 和 `学术搜索` 会共同使用它。

如果扩展后出现网络异常，直接禁用这条订阅的扩展脚本即可恢复原始订阅。

## 部署到 FlClash

`dist/override.js` 使用标准的 `function main(config) { ... return config; }` 入口，可直接作为 FlClash 的覆写脚本使用：

1. 打开“配置”，进入当前订阅的“更多 → 覆写”。
2. 覆写模式选择 **脚本**，不要选择“标准”或“自定义”。
3. 新建脚本，例如命名为 `FlClash 个性化规则`，粘贴 `dist/override.js` 全文并保存。
4. 回到该订阅，在“覆写脚本”中选中刚创建的脚本。
5. 点“预览”，确认存在 `Ai稳定选择`、`Ai测速备用`、`学术搜索`、`学术访问`，确认最后一条仍为原订阅的 `MATCH`，且配置上有 `__flclashRules: { applied: true }` 标记。
6. 启用该订阅；在 `Ai稳定选择` 选择可用的美国节点，在 `学术访问` 选择 `DIRECT`。

FlClash 的脚本是与订阅关联的，不要只在“工具 → 进阶配置 → 脚本”中保存后就结束；必须回到订阅覆写页面选中它。订阅更新后脚本会重新应用，不需要重新粘贴。

如果脚本模式导致“代理/规则”页面消失或预览失败，先取消关联脚本即可恢复原订阅；这属于部分 FlClash 版本的脚本模式兼容问题，不要改用静态“自定义”覆写。Windows 端优先升级到最新稳定版；仍异常时继续使用 Clash Verge Rev。

## 策略组

### `Ai稳定选择`

每次加载订阅时读取当前 `proxies`，用**正向白名单**只保留美国节点（`🇺🇸` / `美国` / `美國` / `United States` / 有界 `US`、`USA`），同时剔除：

- 流量、到期、同步、套餐、官网和客服等提示节点；
- `DIRECT`、`REJECT`、`DNS` 等内置非代理节点。

日、新、德、芬兰等节点大概率被 OpenAI / Anthropic 判地域限制，因此不进 AI 池（订阅原有的全局 `自动选择` 完全不修改，普通业务仍可用它们）。命中白名单的节点即使名字里混有"香港"字样也会保留，防止机场改名误伤。将来要放宽到"美国+日本"之类，改模板里的 `AI_INCLUDE_SOURCE` 即可，不要退回成排除式。

该组使用 `select` 并作为 `Ai+` 的默认出口。客户端会按组名记住人工选择，避免浏览过程中因延迟变化切换公网 IP。

### `Ai测速备用`

备用组用主探针 `https://chatgpt.com/cdn-cgi/trace` 检查候选节点，要求 HTTP `200`，只在人工稳定节点失效时手动切换使用。[Mihomo 的 `expected-status` 说明](https://wiki.metacubex.one/en/config/proxy-groups/)

**探针说明**：

- 主探针验证的是"节点真的能访问 OpenAI"，能筛出"能上网但被 OpenAI 封 IP"的节点；代价是它就是被代理的目标服务本身，属于单点。
- 备用探针 `https://www.gstatic.com/generate_204` 只验证基础连通性，**不能**发现 OpenAI 的 IP 封禁；主探针失效或被 Cloudflare 收紧时才切换到它。
- **修改任何探针 URL 前，请先用浏览器/直连环境确认端点可访问**，再改 `templates/override.js.tpl` 中的 `AI_PROBE_URL` 并重新生成。

### `Ai+`

只包含 `Ai稳定选择` 和 `Ai测速备用`，前者默认优先。不会引用可能间接选中香港节点的原始“手动选择”组。

### `学术搜索`

仅接管 `scholar.google.com` 和 `scholar.google.com.hk`，并与 `Ai+` 共用 `Ai稳定选择`，避免搜索过程中频繁切换出口 IP。YouTube 和其他未明确列出的 Google 子域仍沿用订阅策略。

Gemini 访问有一项有意的例外：`google.com`、`www.google.com`、`accounts.google.com`、`apis.google.com` 和 `ogs.google.com` 使用 `Ai+`。Gemini 会跳转到其中的登录、初始化或 `google.com/sorry` 风控页面；若这些请求落到订阅的 `Google` 组，就可能与 `gemini.google.com` 使用不同公网 IP，从而触发“异常流量”。这里全部使用精确 `DOMAIN`，没有恢复过宽的 `DOMAIN-SUFFIX,google.com`，因此 Scholar 仍进入 `学术搜索`，YouTube 也不受影响。

### `学术访问`

接管 `rules/academic.yaml` 中的出版社和期刊平台，固定提供两个选项：

1. `DIRECT`（默认）：保留本地或机构公网 IP，适用于 Science、Oxford、Elsevier 等订阅识别场景。
2. `Ai+`（备用）：直连遇到地区限制、连接失败或 Cloudflare 验证循环时一键切换。

这是人工 `select`，不会因一次 HTTP 状态码或延迟波动自行改变出口。Mihomo 的自动健康检查没有浏览器 Cookie，而 Science 的无 Cookie 请求可能直接返回 Cloudflare `403`，用它做自动切换会把“可验证访问”误判为“线路不可用”。

`challenges.cloudflare.com` 是多个网站共用的验证域名，规则引擎无法知道它来自 ChatGPT 还是 Science，因此继续固定走 `Ai+` 以保护 ChatGPT。平时 `学术访问` 保持 `DIRECT`；若 Science 出现验证循环，将 `学术访问` 切到 `Ai+` 后刷新，主站与验证请求便会使用同一代理出口。这个切换不影响 Tailscale、普通 Google 或其他直连规则。

## 规则优先级

`rules/index.yml` 从上到下就是最终优先级：

1. 广告 `REJECT`
2. AI/开发服务 `Ai+`
3. Google Scholar `学术搜索`
4. 已确认学术平台 `学术访问`（默认 `DIRECT`，`Ai+` 备用）
5. Tailscale `DIRECT`
6. 其他明确直连 `DIRECT`
7. 原始订阅规则

AI 规则高于宽泛直连规则（例如 ChatGPT 域名先进 `Ai+`，之后其他直连规则才可能兜底）。Copilot 已移到 `direct.yaml`：它在任何地区都可用，不应绑定美国节点。

## 日常修改

分类文件使用 Mihomo classical payload，只写匹配条件，目标策略由 `index.yml` 管理。

添加优先直连、必要时可一键代理的学术站：

```yaml
# rules/academic.yaml
payload:
  - DOMAIN-SUFFIX,new-publisher.example
```

添加需要代理的科研服务：

```yaml
# rules/ai.yaml
payload:
  - DOMAIN-SUFFIX,special-research.example
```

如果新增学术站偶尔出现 Cloudflare Challenge，仍放在 `academic.yaml`，先保持 `学术访问 = DIRECT`；验证循环时临时切换 `学术访问 = Ai+`。只有明确要求长期使用代理、且不依赖本地机构 IP 的科研服务才加入 `ai.yaml`。

修改 Tailscale：

```yaml
# rules/tailscale.yaml
payload:
  - DOMAIN-SUFFIX,ts.net
  - IP-CIDR,100.64.0.0/10,no-resolve
  - IP-CIDR6,fd7a:115c:a1e0::/48,no-resolve
```

修改后执行：

```powershell
python clash.py --check-rules
python clash.py
python clash.py --check
python -m unittest discover -s tests -v
node --test tests/*.js
```

再把更新后的 `dist/override.js` 粘贴到该订阅的扩展脚本。规则没有变化时，代理订阅日常更新不需要重新运行 Python。

## 学术与 Zotero 原则

- 只为实际使用且确有需要的平台添加规则，不默认强制整个 `*.edu.cn` 直连。
- Zotero 使用系统代理/TUN并按目标域名分流，不把整个 Zotero 进程强制到单一代理组。
- Zotero Connector 的 `127.0.0.1:23119` 是本地通信，应保持回环直连。
- Mihomo 嗅探只帮助从 HTTP/TLS/QUIC 流量恢复域名，不能修复下载到 99% 中断等传输问题。
- Cambridge、JSTOR、bioRxiv、medRxiv、Crossref/DOI、ORCID、OpenAlex 等作为候选平台，确认真实访问需求后再逐项启用。

## 本次清理和补充

- Tailscale 使用明确的 `tailscale.com`、`tailscale.io`、`ts.net`，并覆盖 Tailnet IPv4/IPv6。
- Oxford 更新为 `oup.com`；补齐 Elsevier CDN、Springer Nature、Clarivate/Web of Science 依赖。
- 补齐 Claude、Grok、Copilot、Docker 和 Hugging Face 的当前服务域名。
- 删除 `DOMAIN-KEYWORD,google`、`216.239.0.0/16`、`example.com`、重复条目和被父域完整覆盖的子域。
- 广告规则置顶；没有用后缀规则把整个 Google、YouTube 导向 `Ai+`。仅将 Gemini 必需的 Google 根域、登录和初始化端点固定到同一 AI 出口，避免会话中途更换公网 IP。
- 修复原订阅 `Apple` 与 `AppleDev` provider 缓存路径冲突。
- `漏网之鱼` 将 `DIRECT` 放在第一项，但保留原有其他选择。
- ChatGPT 核心域名由本项目明确接管，不再完全依赖订阅的远程 OpenAI provider。
- Science、PNAS、Oxford Academic、Taylor & Francis 和 Cell 改为 `学术访问`：默认恢复直连和机构 IP，需要处理 Cloudflare Challenge 时可一键切到 `Ai+`，不再永久占用代理出口。
- 原 `Ai自动选择` 被替换为“人工稳定出口优先、ChatGPT 测速备用”，避免只因 Google 延迟变化切换 AI 公网 IP。
- Claude 修复：补齐 `claude.ai`（Anthropic 主域/网页入口，此前实测直连会跳转 `claude.com/app-unavailable-in-region`）、`anthropic.com`、`claudeusercontent.com`；旧注释“订阅已覆盖 claude.ai”是错误的，已删除。
- AI 节点选择从“排除港澳台”改为“正向美国白名单”（`AI_INCLUDE`）；`AI_EXCLUDE` 收窄为只剔除机场信息行（Expire/Traffic/Sync/官网等）。
- 覆写脚本支持 `proxy-providers` 型订阅（`Ai+` 带运行时 filter），并在成功/降级时留下 `__flclashRules` 标记；缺组只降级不再整体放弃。
- 测速探针增加备用端点说明（`gstatic.com/generate_204`）及主/备筛选能力差异文档。
- 删除实测无代理收益的 `default.exp-tas.com`、`intercom.io`、`roboflow.com`，删除被 `googleapis.com` 覆盖的 `generativelanguage.googleapis.com`；`githubcopilot.com` 移到 `direct.yaml`。
- `direct.yaml` 中的 Adobe 域名保留并注明理由：多数是独立注册域，无法无损压缩为 `adobe.com`/`adobe.io` 后缀。
- `tailscale.yaml` 增加共享服务器 CGNAT 警告；本仓库主要面向 Windows/macOS 单用户桌面。
- `fixProviderPaths` 的 Apple/AppleDev 路径修正已标注为特定订阅专用 hack，换订阅需重新评估。

## 命令

```text
python clash.py                         生成 override.js 和 server-policy.yaml
python clash.py --check                 检查规则及两个生成物是否一致
python clash.py --check-rules           只检查 rules/，不读取订阅
python webui.py                         启动本地图形界面（默认 http://127.0.0.1:8765）
```

## 图形界面

`webui.py` 提供本地网页界面，用于快速添加规则并生成脚本：

```powershell
python webui.py                # 默认 http://127.0.0.1:8765，自动打开浏览器
python webui.py --port 9000    # 指定端口
python webui.py --no-browser   # 不自动打开浏览器
```

功能：

- 粘贴网址后自动提取注册域，生成 `DOMAIN-SUFFIX` / `DOMAIN` / `DOMAIN-KEYWORD` 候选并要求确认；
- 添加前检测完全重复、被更高优先级规则覆盖等冲突，存在硬冲突时阻止写入；
- 选择目标规则文件后一键追加（保留注释），失败自动回滚；
- 点击"生成 dist/override.js"完成最终脚本输出。

服务只监听 `127.0.0.1`，不联网、不读写规则以外的文件。日常修改也可以继续直接编辑 `rules/*.yaml`。

## 服务器用户级 Mihomo

`dist/server-policy.yaml` 只提供策略组和规则。完整服务器配置中的 subscription URL、认证 Listener、provider 缓存和节点内容只能保存在服务器权限收紧的目录，不得进入本仓库。

服务器策略固定为：

- `Ai+`：动态使用 `subscription` provider，并用与美国白名单一致的 `filter` 只选美国节点；
- `学术搜索`：默认 `Ai+`，保留 `DIRECT`；
- `学术访问`：默认 `DIRECT`，保留 `Ai+`；
- SEA-AD S3：精确 `DIRECT`；
- 未命中规则：`MATCH,DIRECT`。

部署、认证边界、手动 systemd 服务、测试与回滚见 [服务器 Mihomo 维护说明](docs/服务器Mihomo维护说明.md)。

## GitHub 同步与隐私

仓库只同步规则、构建工具、测试、README 和生成的无敏感信息脚本。无论公开使用还是自行派生，提交前都应检查：

```powershell
git status --short
git ls-files
```

`git ls-files` 不应出现 `local/`、订阅 YAML、节点服务器、UUID、密码、订阅令牌、provider 缓存或合并成品。

```powershell
git add -- rules templates dist README.md clash.py tests .github .gitignore requirements.txt
git commit -m "Add subscription extension workflow"
git push
```

`Loyalsoldier/clash-rules` 等公共项目提供通用的国内外、广告、GFW 和 IP 分类；代理订阅通常已经包含同类 provider。本项目只维护明确的学术、AI 与 Tailscale 分流诉求，避免整套重复引入造成冲突。

## 许可证

本项目采用 [MIT License](LICENSE)。使用、修改或分发前，请自行确认代理订阅服务条款及所在地区的法律要求；本仓库不提供订阅、节点或网络服务。
