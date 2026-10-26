# 服务器 Mihomo 策略部署

本仓库只负责规则源、策略组、桌面 `override.js` 与服务器 `server-policy.yaml`。配置导入、序列化、运行控制、核心校验及测速由独立的 [mihomo-userctl](https://github.com/liuzq1103/mihomo-userctl) 负责。

## 产物与兼容范围

`dist/override.js` 用于 Clash Verge Rev / FlClash 桌面订阅脚本，成功和降级结果默认保留 `__flclashRules` 状态标记。服务器优先使用 `dist/server-policy.yaml`，它是策略片段，包含组和规则，需要本地 `subscription` provider 及既有运行配置，不是完整独立配置，不能直接作为 `mihomo -f` 输入启动。

mihomoctl **1.4.1 不直接兼容**桌面脚本的默认状态标记。其脚本输出白名单只允许修改 `proxy-groups`、`rules`、`rule-providers`，新增 `__flclashRules` 会被拒绝，`--flclash-compat` 也未移除或接纳该字段。不要手工删除生成物中的标记作为长期方案；本指南不承诺其他版本已支持脚本。

命令按 **mihomoctl v1.4.1 / `3bf2b78187b9de619664f8e1194f1d274af65bd5` 的源码**核对：[命令定义](https://github.com/liuzq1103/mihomo-userctl/blob/v1.4.1/mihomoctl/command_spec.py)、[订阅导入](https://github.com/liuzq1103/mihomo-userctl/blob/v1.4.1/mihomoctl/controller/controller_subscriptions.py)、[脚本白名单](https://github.com/liuzq1103/mihomo-userctl/blob/v1.4.1/mihomoctl/controller/controller_policy.py)、[订阅教程](https://github.com/liuzq1103/mihomo-userctl/blob/v1.4.1/docs/zh-CN/subscriptions.md)。这不代表生产服务器、真实订阅或实际业务的运行验收。执行前检查 `mihomoctl version` 和相关 `--help`；接口不同应停止并核对。

## 策略语义与 provider 引用

| 组 | 节点来源与默认行为 |
|---|---|
| `PROXY` | 直接 `use: [subscription]`；只排除信息行，全地区通用测速 |
| `Ai稳定选择` | 直接引用 provider；美国白名单，人工选择稳定出口 |
| `Ai测速备用` | 直接引用 provider；同一美国白名单，ChatGPT trace 探针要求 HTTP 200 |
| `Dev+` | 直接引用 provider，筛选美国或香港；另含默认项 `PROXY`，该项可选全地区节点 |
| `Ai+` | 间接引用 `Ai稳定选择`、`Ai测速备用`，稳定优先 |
| `学术搜索` | 间接引用 `Ai+`，备用 `DIRECT` |
| `学术访问` | 默认 `DIRECT`，备用间接引用 `Ai+` |

只有四个组直接引用 provider，所有 `use` 都必须能找到同一导入文件中的 `subscription` 定义。不要给 `Ai+` 增加绕过美国筛选的 `use`。

规则按顺序首个匹配生效：优先直连例外 → Scholar → AI → 开发 → 学术 → `MATCH,DIRECT`。未命中流量直连是设计行为。桌面专属广告、Tailscale 和 Adobe/Microsoft 规则不进入服务器产物。开发规则进入 `Dev+`，其默认 `PROXY` 不限美港。学术访问默认直连以保留机构出口身份。

`generate_204` 成功仅说明探针连通；ChatGPT trace 返回 200 也只说明该端点的本次请求成功，不能保证登录、地区权限、会话或 ChatGPT/Claude 等完整业务可用。

## 服务器本地组合示例

前提：已按 mihomo-userctl 官方流程建立受管运行时。将选定版本的 `examples/server-provider.example.yaml` 和 `dist/server-policy.yaml` 放在服务器 `$HOME/flclash-rules` 下的对应子目录；Release 附件可按此目录摆放。以下命令由部署者在**服务器本地**执行，本项目发布过程不操作服务器：

```bash
umask 077
mkdir -p "$HOME/private/flclash"
chmod 700 "$HOME/private" "$HOME/private/flclash"
cp "$HOME/flclash-rules/examples/server-provider.example.yaml" "$HOME/private/flclash/provider.yaml"
chmod 600 "$HOME/private/flclash/provider.yaml"
```

用本地编辑器打开 `$HOME/private/flclash/provider.yaml`，把 `url:` 后整个 `https://subscription.example.invalid/REPLACE_WITH_PRIVATE_SUBSCRIPTION` 替换成自己的 HTTPS 订阅 URL。占位域名有意不可用，未填写不要导入。真实 URL 只放在服务器私有副本，不放到命令行、仓库、issue、截图或发布资产。

provider 名称固定为 `subscription`；缓存路径 `./proxy_providers/subscription.yaml` 相对于管理器当前的**核心工作目录**解析，不是导入文件目录或 Shell 当前目录。缓存含节点秘密，必须留在服务器私有目录。不能指向活动配置、上级目录、其他 provider 的缓存或不可信符号链接；导入器会检查路径。

每次从两个文件重新组合并覆盖输出，不要追加到旧文件：

```bash
umask 077
cat "$HOME/private/flclash/provider.yaml" \
    "$HOME/flclash-rules/dist/server-policy.yaml" \
    > "$HOME/private/flclash/routing-policy.yaml"
chmod 600 "$HOME/private/flclash/routing-policy.yaml"
```

示例末尾带换行且没有 YAML 多文档分隔符，组合后仍是一个映射，包含 `proxy-providers`、`proxy-groups`、`rules`。这是**完整路由策略导入文件**，仍不是完整服务器配置，不包含 listener 或认证。保留片段多行格式和整行过滤正则，不要折行或文字替换改变正则。

## 预览、保存与运行态

```bash
mihomoctl version
mihomoctl subscription preview --source-file "$HOME/private/flclash/routing-policy.yaml" --policy provider --json
```

明确使用 `provider` 完整策略模式。`nodes` 只导入节点，不安装本项目策略；`auto` 按是否存在路由字段推断模式。本例显式指定便于核对。provider 模式替换五类路由字段：`proxies`、`proxy-providers`、`proxy-groups`、`rules`、`rule-providers`；未提供的字段变为空列表或字典，既有内联节点和 rule-provider 可能被清除。不能只导入裸 `server-policy.yaml`，否则缺失 `subscription` 定义。

preview 保存私有候选并检查，但不保存活动配置、不启动或重启。只在本地审阅字段变更、删除项、组、规则、验证结果和摘要。JSON 信封的候选 ID 和 SHA256 在 `data.legacy.id`、`data.legacy.sha256`。将审阅通过的值填入占位位置：

```bash
mihomoctl subscription apply PREVIEW_ID --sha256 CANDIDATE_SHA256
mihomoctl config validate
```

apply 检查原配置漂移、候选摘要、字段边界和核心校验，再事务保存；保存不等于加载运行态。任一步失败都先停止并排障；配置变化后重新 preview，不编辑候选绕过校验。

服务未运行时显式启动：

```bash
mihomoctl start
```

服务已运行、需要加载新保存配置时显式重启：

```bash
mihomoctl restart
```

随后检查：

```bash
mihomoctl status
mihomoctl health check
mihomoctl groups
mihomoctl providers
mihomoctl logs --lines 100
mihomoctl exec -- curl --fail --head https://chatgpt.com
```

按实际组成员在 `Ai稳定选择` 人工选可用美国节点。节点名、日志、连接详情和 preview 输出只在本地审阅，不发布。端口、本地健康检查或 HTTP 成功都不能单独证明目标命中正确规则或业务可用；需对照实际 mode、目标规则、组选择和真实请求验证。

## 旧接口与跨仓库限制

本指南不混用旧 Shell 函数、手工替换活动配置和历史 systemd 流程；`ready` 已退出当前接口，使用 `health check`。桌面使用方法见 README 的桌面章节。

以下现场问题由 mihomo-userctl 修复，本仓库不改变策略来绕过：默认标记与字段白名单不兼容；导入后列表或字典压成一行；核心校验超时、缓存未复用和重复校验；provider 节点测速被判 `unknown-node`；权限错误仅显示 `InstallError`；TUI 保存失败阶段和运行状态不明确。

本仓库发布的 YAML 保持多行，但不能保证旧导入器保存后保持格式。失败时记录脱敏版本、阶段和退出状态，不把保存失败报告成运行成功，也不承诺未经验证的新版本已解决问题。

## 修改、验证与隐私

只修改规则源、模板或生成器，再生成产物：

```powershell
python clash.py --check-rules
python clash.py
python clash.py --check
python -m unittest discover -s tests -v
node --test tests/*.js
git diff --check
```

测试数量以实际输出为准。示例组合、provider 引用、缓存路径、策略目标、正则往返及桌面标记均有离线测试；离线测试不证明服务器或真实订阅可用。

真实订阅、节点凭据、listener 认证、控制器密钥、完整配置、候选和缓存仅存服务器权限收紧的目录及私有备份。不要提交编辑后的示例。回滚使用事先准备并验证的私有备份及控制器对应版本说明，恢复后重新校验并显式加载；历史现场路径不是通用回滚命令。

发布与审核要求见 [发布规范](RELEASING.md)。
