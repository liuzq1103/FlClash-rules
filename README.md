# FlClash 自定义规则合并工具

把个人分流规则合并到树洞订阅中，并输出一份可直接导入 FlClash 的 Mihomo 配置。规则按用途拆分，日常修改学术网站或 Tailscale 时不需要改 Python。

## 目录结构

```text
.
├── clash.py
├── requirements.txt
├── rules/
│   ├── index.yml       # 规则文件、策略目标与优先级
│   ├── reject.yaml     # 广告拦截
│   ├── ai.yaml         # AI、开发服务、学术代理例外
│   ├── academic.yaml   # 学术网站直连
│   ├── tailscale.yaml  # Tailscale 域名与 IP
│   └── direct.yaml     # Microsoft、Adobe 等其他直连
├── tests/
├── .github/workflows/validate.yml
└── local/              # 被 Git 忽略，可能包含节点凭据
    ├── gw树洞.yaml
    └── output/merged_gw树洞.yaml
```

## 首次使用

```powershell
python -m pip install -r requirements.txt
python clash.py --check-rules
```

将当前订阅保存为 `local/gw树洞.yaml`，然后执行：

```powershell
python clash.py --check
python clash.py
```

把生成的 `local/output/merged_gw树洞.yaml` 导入 FlClash。以后订阅更新时，只需替换 `local/gw树洞.yaml` 并重新运行以上两个命令。

## 修改规则

规则文件采用 Mihomo classical payload，只写匹配条件，不在行尾写策略组。目标策略由 `rules/index.yml` 统一指定。

### 添加学术网站直连

编辑 `rules/academic.yaml`：

```yaml
payload:
  - DOMAIN-SUFFIX,nature.com
  - DOMAIN-SUFFIX,new-publisher.example
```

`DOMAIN-SUFFIX` 会匹配主域及所有子域，通常比枚举 `www`、`api`、`static` 更容易维护。

### 添加需要代理的学术例外

如果某个科研网站直连不可用，将它放到 `rules/ai.yaml`。AI 规则优先于学术直连，因此可以覆盖更宽的直连后缀：

```yaml
payload:
  - DOMAIN-SUFFIX,special-research.example
```

### 修改 Tailscale

编辑 `rules/tailscale.yaml`。域名使用后缀，IP 网段加 `no-resolve`：

```yaml
payload:
  - DOMAIN-SUFFIX,ts.net
  - IP-CIDR,100.64.0.0/10,no-resolve
  - IP-CIDR6,fd7a:115c:a1e0::/48,no-resolve
```

### 修改后检查

```powershell
python clash.py --check-rules
python -m unittest discover -s tests -v
python clash.py
```

## 规则优先级

`rules/index.yml` 的顺序就是最终匹配顺序：

1. `REJECT`：先拦截广告，避免被 Google/AI 规则抢先命中。
2. `Ai+`：AI 服务和学术代理例外。
3. 学术 `DIRECT`。
4. Tailscale `DIRECT`。
5. Microsoft、Adobe 等其他 `DIRECT`。
6. 订阅原有规则。

Mihomo 从上向下匹配，第一条命中的规则生效。除非是在设计有意覆盖，否则不要在多个文件重复添加相同域名。

## 本次重构的主要变化

- 新建 `Ai自动选择`，仅 AI 流量排除港澳台和套餐提示节点；订阅原有全局 `自动选择` 不再受影响。
- `Ai+` 默认使用 `Ai自动选择`；`漏网之鱼` 默认使用 `DIRECT`。
- Tailscale 补充 IPv6 Tailnet 网段，并用明确域名后缀替代关键词。
- Oxford 改用当前 `oup.com`；Elsevier 补充资源/CDN；Springer Nature、Clarivate 和 Web of Science 补充相关依赖。
- GitHub Copilot、Docker、Hugging Face、Claude 和 Grok 补充官方服务域名。
- 删除 `example.com`、重复 OpenAI/Claude/Gemini、过宽 Google 关键词和 `216.239.0.0/16`。
- 广告规则提升到最高优先级，使 Google Ads 拦截真正生效。
- 修复订阅中 `Apple` 与 `AppleDev` 使用同一 provider 缓存路径的问题。

未默认加入 Cambridge、JSTOR、bioRxiv、medRxiv、Crossref/DOI、ORCID 等新平台。如果以后确认它们也需要强制直连，再逐项添加到 `academic.yaml`，避免不必要地改变现有路由。

## 命令

```text
python clash.py                    使用 local/gw树洞.yaml 生成配置
python clash.py other.yaml         处理指定订阅
python clash.py --check            校验默认订阅和规则，不写文件
python clash.py --check-rules      只校验 rules/，适合 CI
```

输出始终写入 `local/output/merged_<原文件名>`。

## GitHub 同步与隐私

GitHub 私有仓库只保存脚本、规则、README、测试与 CI。以下内容绝不能提交：

- 原始订阅 YAML
- 合并后的配置
- provider 缓存
- 节点服务器、UUID、密码或订阅令牌

`local/` 已被 `.gitignore` 整体排除。提交前仍应检查：

```powershell
git status --short
git ls-files
```

规则更新后可执行：

```powershell
git add -- rules README.md clash.py tests .github .gitignore requirements.txt
git commit -m "Update custom routing rules"
git push
```

GitHub Actions 只使用合成测试配置，不会读取或生成真实订阅。

## 公共规则集说明

`Loyalsoldier/clash-rules` 等项目提供通用的中国直连、GFW、广告和 IP 分类。本订阅已经包含多组同类 provider，因此本工具不再整套引入，以免重复和冲突。个人学术访问、Tailscale 以及 AI 禁用港澳台节点属于本项目单独维护的策略。

## 常见错误

- `subscription not found`：确认文件位于 `local/gw树洞.yaml`，或在命令中传入路径。
- `No module named yaml`：运行 `python -m pip install -r requirements.txt`。
- `duplicate rule` / `redundant rule`：删除重复项或已被父域后缀覆盖的子域。
- `missing policy target`：新订阅缺少 `Ai+` 或 `漏网之鱼` 等脚本所需策略组，应先检查订阅结构变化。
