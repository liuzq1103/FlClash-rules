# FlClash 个性化分流规则

本项目把机场订阅当作动态节点源，把个人规则编译成 Clash Verge Rev / FlClash 可共用的 **JavaScript 扩展脚本**。客户端每次更新订阅后都会基于最新节点重新生成策略组，不复制、不保存完整订阅配置。

> 主客户端推荐 Clash Verge Rev。FlClash 使用“脚本”覆写模式；不要使用“自定义 → 一键填入”保存整套节点和策略组，后者是静态副本，节点名称变化后容易失效。

## 工作方式

```text
原始订阅（自动更新节点）
  → 订阅级 dist/override.js
  → 动态 AI/学术策略组 + 个性化规则
  → Mihomo 运行配置
```

- 原始订阅继续负责节点、DNS、通用 provider 和基础分流。
- `rules/*.yaml` 是个人规则的唯一来源。
- `clash.py` 将分类规则展开为普通 Mihomo 规则并生成 `dist/override.js`。
- 脚本不联网、不读取 GitHub、不包含订阅地址或节点凭据。
- 脚本在副本上修改并完成自检；任何异常都返回原始配置。

## 目录

```text
FlClash/
├── clash.py
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
├── dist/
│   └── override.js     # 生成后粘贴到客户端
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

1. 在 Clash Verge Rev 中保留并更新原始 `gw树洞.yaml` 订阅。
2. 给这条订阅配置“扩展脚本”，粘贴 `dist/override.js` 的完整内容。
3. 不要把脚本放到“全局扩展脚本”；全局扩展配置也保持为空。
4. 先使用“预览”确认存在 `Ai稳定选择`、`Ai测速备用`、`学术搜索`、`学术访问`，且规则仍以原订阅的 `MATCH` 结束。
5. 启用订阅后，在 `Ai稳定选择` 中固定一个可正常打开 ChatGPT 的非港澳台节点；`Ai+` 和 `学术搜索` 会共同使用它。

如果扩展后出现网络异常，直接禁用这条订阅的扩展脚本即可恢复原始订阅。

## 部署到 FlClash

`dist/override.js` 使用标准的 `function main(config) { ... return config; }` 入口，可直接作为 FlClash 的覆写脚本使用：

1. 打开“配置”，进入当前订阅的“更多 → 覆写”。
2. 覆写模式选择 **脚本**，不要选择“标准”或“自定义”。
3. 新建脚本，例如命名为 `FlClash 个性化规则`，粘贴 `dist/override.js` 全文并保存。
4. 回到该订阅，在“覆写脚本”中选中刚创建的脚本。
5. 点“预览”，确认存在 `Ai稳定选择`、`Ai测速备用`、`学术搜索`、`学术访问`，并确认最后一条仍为原订阅的 `MATCH`。
6. 启用该订阅；在 `Ai稳定选择` 选择可用的非港澳台节点，在 `学术访问` 选择 `DIRECT`。

FlClash 的脚本是与订阅关联的，不要只在“工具 → 进阶配置 → 脚本”中保存后就结束；必须回到订阅覆写页面选中它。订阅更新后脚本会重新应用，不需要重新粘贴。

如果脚本模式导致“代理/规则”页面消失或预览失败，先取消关联脚本即可恢复原订阅；这属于部分 FlClash 版本的脚本模式兼容问题，不要改用静态“自定义”覆写。Windows 端优先升级到最新稳定版；仍异常时继续使用 Clash Verge Rev。

## 策略组

### `Ai稳定选择`

每次加载订阅时读取当前 `proxies`，排除：

- 香港、澳门、台湾节点和常见中英文缩写；
- 流量、到期、同步、套餐、官网和客服等提示节点；
- `DIRECT` 等非代理节点。

该组使用 `select` 并作为 `Ai+` 的默认出口。客户端会按组名记住人工选择，避免浏览过程中因延迟变化切换公网 IP。订阅原有的全局 `自动选择` 完全不修改，因此普通业务仍可继续使用香港节点。

### `Ai测速备用`

备用组使用 `https://chatgpt.com/cdn-cgi/trace` 检查候选节点，要求 HTTP `200`，只在人工稳定节点失效时手动切换使用。它不再用 Google 204 代替 ChatGPT 可达性检查，也不再作为 `Ai+` 默认项。[Mihomo 的 `expected-status` 说明](https://wiki.metacubex.one/en/config/proxy-groups/)

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

AI 规则高于宽泛直连规则，例如 Copilot 会先进入 `Ai+`，之后 Microsoft 才可能匹配 `DIRECT`。

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

再把更新后的 `dist/override.js` 粘贴到该订阅的扩展脚本。规则没有变化时，机场订阅日常更新不需要重新运行 Python。

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

## 命令

```text
python clash.py                         生成 dist/override.js
python clash.py --check                 检查规则和生成物是否一致
python clash.py --check-rules           只检查 rules/，不读取订阅
```

## GitHub 同步与隐私

私有仓库只同步规则、构建工具、测试、README 和生成的无敏感信息脚本。提交前检查：

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

`Loyalsoldier/clash-rules` 等公共项目提供通用的国内外、广告、GFW 和 IP 分类；机场订阅已经包含同类 provider。本项目只维护个人学术、AI 与 Tailscale 诉求，避免整套重复引入造成冲突。
