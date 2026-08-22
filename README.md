# FlClash 个性化分流规则

本项目把机场订阅当作动态节点源，把个人规则编译成 Clash Verge Rev 的**订阅级扩展脚本**。客户端每次更新订阅后都会基于最新节点重新生成策略组，不再复制或长期保存一份容易失效的完整配置。

> 主客户端推荐 Clash Verge Rev。FlClash 可作为备用，但不要使用“自定义覆写 → 一键填入”保存整套节点和策略组；节点名称变化后，这种静态覆写容易失效。

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
└── local/              # Git 忽略：订阅和应急输出
    ├── gw树洞.yaml
    └── output/
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
4. 先使用“预览”确认存在 `Ai稳定选择`、`Ai测速备用`、`学术搜索`，且规则仍以原订阅的 `MATCH` 结束。
5. 启用订阅后，在 `Ai稳定选择` 中固定一个可正常打开 ChatGPT 的非港澳台节点；`Ai+` 和 `学术搜索` 会共同使用它。

如果扩展后出现网络异常，直接禁用这条订阅的扩展脚本即可恢复原始订阅。

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

仅接管 `scholar.google.com` 和 `scholar.google.com.hk`，并与 `Ai+` 共用 `Ai稳定选择`，避免搜索过程中频繁切换出口 IP。普通 Google 和 YouTube 沿用订阅策略。

## 规则优先级

`rules/index.yml` 从上到下就是最终优先级：

1. 广告 `REJECT`
2. AI/开发服务 `Ai+`
3. Google Scholar `学术搜索`
4. 已确认学术平台 `DIRECT`
5. Tailscale `DIRECT`
6. 其他明确直连 `DIRECT`
7. 原始订阅规则

AI 规则高于宽泛直连规则，例如 Copilot 会先进入 `Ai+`，之后 Microsoft 才可能匹配 `DIRECT`。

## 日常修改

分类文件使用 Mihomo classical payload，只写匹配条件，目标策略由 `index.yml` 管理。

添加学术直连：

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

如果网站返回 Cloudflare Challenge，主站和 `challenges.cloudflare.com` 必须使用同一策略。此类学术域名应加入 `rules/ai.yaml`，并在 `rules/index.yml` 的 `cloudflare-session-affinity` 约束中登记；不要只把主站放进 `academic.yaml` 直连。校验器会在相关规则被移动到不同策略时直接报错。

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
- 广告规则置顶；普通 Google、YouTube 不再被自定义规则整体导向 `Ai+`。
- 修复原订阅 `Apple` 与 `AppleDev` provider 缓存路径冲突。
- `漏网之鱼` 将 `DIRECT` 放在第一项，但保留原有其他选择。
- ChatGPT 核心域名由本项目明确接管，不再完全依赖订阅的远程 OpenAI provider。
- 实测会触发 Cloudflare Challenge 的 Science、PNAS、Oxford Academic、Taylor & Francis 和 Cell 改走 `Ai+`，与验证资源保持同一出口。
- 原 `Ai自动选择` 被替换为“人工稳定出口优先、ChatGPT 测速备用”，避免只因 Google 延迟变化切换 AI 公网 IP。

## 命令

```text
python clash.py                         生成 dist/override.js
python clash.py --check                 检查规则、生成物；本地订阅存在时兼容性检查
python clash.py --check-rules           只检查 rules/，不读取订阅
python clash.py --legacy-merge          应急生成 local/output/merged_gw树洞.yaml
python clash.py --legacy-merge x.yaml   应急处理指定订阅
```

完整合并 YAML 只用于诊断和应急，不作为日常导入方式。

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
