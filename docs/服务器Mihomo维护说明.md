# `liuzq` 服务器 Mihomo 策略维护说明

本文描述 `D:\Desktop\技术\FlClash` 如何生成服务器 Mihomo 的无秘密策略片段，以及如何安全维护服务器用户级 Mihomo。

## 0. 两个项目必须分开

```text
D:\Desktop\技术\FlClash
  → PC 端 Clash/FlClash 规则脚本
  → 同一规则源生成无秘密 dist/server-policy.yaml

D:\Desktop\技术\mihomo-userctl
  → 服务器端用户级服务控制和 Shell 集成
  → 安装 mihomoctl、shell.bash、common.bash
```

`FlClash` 是规则编译项目，负责回答“进入 Mihomo 后命中哪个策略”；
`mihomo-userctl` 是服务器运行控制项目，负责回答“这个 Shell 或命令是否进入
Mihomo”。两个目录是独立 Git 仓库，不互相复制源码、不共享秘密，也不能把
`mihomo-userctl` 子目录提交到 FlClash 仓库。

## 1. 文件职责

```text
rules/index.yml
  → 定义规则文件顺序和目标策略

rules/*.yaml
  → 自定义域名、IP 和目标策略的唯一来源

clash.py
  → 校验规则并生成两个产物

dist/override.js
  → Windows Clash Verge Rev / FlClash 订阅扩展脚本

dist/server-policy.yaml
  → 服务器 Mihomo 的策略组和规则片段
```

服务器完整 `config.yaml` 不在仓库。它由以下内容组合：

```text
服务器本地 Listener 与认证
  + 服务器本地 subscription proxy-provider
  + dist/server-policy.yaml
```

## 2. server-policy 的固定设计

`dist/server-policy.yaml` 包含：

- `Ai+`：`url-test`，动态使用名为 `subscription` 的 provider；
- `学术搜索`：`Ai+` 在前，`DIRECT` 备选；
- `学术访问`：`DIRECT` 在前，`Ai+` 备选；
- 129 条自定义规则；
- 最后一条 `MATCH,DIRECT`。

它不包含：

- `proxy-providers:`；
- 订阅 URL；
- Listener 用户名或密码；
- 节点配置；
- provider 缓存；
- VS Code 认证 URL。

## 3. 生成与验证

在仓库根目录：

```powershell
python clash.py --check-rules
python clash.py
python clash.py --check
python -m unittest discover -s tests -p "test_*.py"
node --test tests/*.js
git diff --check
```

当前期望：

```text
规则数：129
Python 测试：15
Node 测试：5
```

敏感信息扫描：

```powershell
rg -n -i "(subscription[_-]?url|password|secret|token):|https?://[^[:space:]]+@" `
  dist/server-policy.yaml clash.py tests/test_clash.py
```

正常结果为空。

## 4. 修改规则

不要直接编辑 `dist/override.js` 或 `dist/server-policy.yaml`。它们是生成物。

正确流程：

1. 在对应的 `rules/*.yaml` 修改源规则；
2. 检查 `rules/index.yml` 中优先级；
3. 运行全部生成和测试命令；
4. 查看 `git diff`；
5. 确认没有订阅、节点或凭据；
6. 再部署生成物。

规则按文件和文件内顺序展开。越精确、越重要的规则应越靠前。

## 5. SEA-AD 保险规则

服务器和 Windows 共享精确规则：

```text
DOMAIN,sea-ad-single-cell-profiling.s3.amazonaws.com,DIRECT
```

不要改成：

```text
DOMAIN-SUFFIX,amazonaws.com,DIRECT
```

原因是整个 AWS 域名空间中可能存在需要代理的其他服务。精确域名只保护已确认的大数据入口。

## 6. 部署 server-policy

部署前：

```powershell
python clash.py --check
git diff --check
```

将无秘密片段复制到服务器允许目录：

```powershell
scp dist/server-policy.yaml `
  "liuzq细胞房:/home/liuzq/.local/share/mihomo/server-policy.yaml"
```

服务器文件权限：

```bash
chmod 600 ~/.local/share/mihomo/server-policy.yaml
```

完整配置必须在服务器安全构建，不能把订阅 URL或密码写回仓库。

更新完整配置前始终：

```bash
~/.local/bin/mihomo -t \
  -d ~/.local/share/mihomo \
  -f ~/.config/mihomo/config.yaml
```

然后：

```bash
mihomoctl restart
proxy_status
```

## 7. 服务运维

```bash
mihomoctl start
mihomoctl stop
mihomoctl restart
mihomoctl status
mihomoctl ready
mihomoctl doctor
mihomoctl logs --lines 100
```

`mihomo_start`、`mihomo_stop` 等旧名称在 `0.x` 阶段只是兼容包装器；文档和
新的自动化统一使用 `mihomoctl`。控制器来自独立的 `mihomo-userctl` 仓库，
不是本 FlClash 规则生成器的一部分。

服务必须保持：

```bash
systemctl --user is-enabled mihomo
# disabled
```

禁止：

```text
sudo systemctl
systemctl --user enable mihomo
loginctl enable-linger
/etc/systemd/system
root service
```

## 8. 启动就绪语义

订阅 provider 和 `Ai+` url-test 初始化是异步的。测试中观察到：

```text
端口刚出现
  → 立即请求可能 502
  → provider 加载和健康检查完成
  → 请求正常
```

因此：

- 不要用“17890 已监听”作为唯一成功标准；
- 使用 `mihomoctl start` 或 `mihomoctl restart`；
- 两个命令会执行认证请求并最多等待 30 秒；
- 如果未 ready，应运行 `mihomoctl doctor` 和 `mihomoctl logs --lines 100`，不要绕过检查。

## 9. 认证与秘密

秘密只允许存在于：

```text
~/.config/mihomo/config.yaml
~/.config/mihomo/client.env
~/.local/share/mihomo/proxy_providers/subscription.yaml
权限收紧的备份
```

不得：

- 把订阅 URL 放进命令行；
- 把密码作为 curl 参数；
- 打印完整 `http.proxy`；
- 提交 provider 缓存；
- 把旧 Windows Listener 密码复制给服务器 Mihomo；
- 在报告中显示节点或凭据。

测试 curl 时，通过环境变量传递代理 URL，避免出现在进程参数中。

## 10. 规则验证

启动后可用日志确认：

```bash
with_proxy curl -I https://chatgpt.com
with_proxy curl -I https://github.com
with_proxy curl -I https://www.science.org
with_proxy curl -I https://sea-ad-single-cell-profiling.s3.amazonaws.com/
mihomo_logs --since '5 minutes ago'
```

期望：

```text
chatgpt.com → Ai+
github.com → Ai+
science.org → 学术访问[DIRECT]
SEA-AD → DIRECT
```

未认证请求必须失败。

## 11. 大文件原则

规则只是保险，默认 Shell 直连才是根本控制：

```bash
proxy_off
proxy_status
axel -n 10 'large-file-url'
```

必须看到 `shell=direct`。

## 12. 回滚

服务器备份：

```text
/home/liuzq/.config/mihomo/backups/20260824-112605
/home/liuzq/.config/mihomo/backups/20260824-113928-cutover
/home/liuzq/.local/share/mihomo/backups/20260824-112605
/home/liuzq/.local/share/mihomo/backups/migration-tools-20260824-141750
```

回滚流程：

1. `proxy_off` 后执行 `mihomoctl stop`；
2. 恢复目标配置到候选路径；
3. 检查权限；
4. 执行 `mihomo -t`；
5. 原子替换活动文件；
6. `systemctl --user daemon-reload`；
7. `mihomoctl start`；
8. 验证默认直连和 service disabled。

不要把 PC `RemoteForward` 恢复成长期架构。

## 13. 最终迁移状态

已完成：

- v1.19.30 安装和 SHA256 验证；
- server-policy 生成器和测试；
- 17894 完整隔离验收；
- 受管 PC 隧道精确停止；
- 正式 17890 启动；
- `.bashrc`、Codex payload 和 VS Code 设置迁移；
- 用户服务生命周期测试。
- `.bashrc` 中约 200 行实现已拆到独立 `mihomo-userctl` 项目；
- `.bashrc` 只保留权限校验和 `source shell.bash` 的短 loader；
- `mihomoctl` 与 Shell 函数的隔离测试为 15/15 通过。

- 用户已确认普通新 Codex/VS Code 会话连接成功；
- 两个旧 `liuzq` 隧道 Host 已精确移除；
- 旧脚本和编码备份已归档，活动状态文件不存在；
- Windows `17891` Listener 已删除并热重载；
- 常规 Windows `7890`、系统代理和清理前实际 TUN 状态保持；
- 旧 private-proxy 活动文件已归档；
- 非 `liuzq` Host 块哈希、端口、运行时语义和敏感信息扫描进入最终验收。

范围外服务器 `127.0.0.1:7890` 无论是否存在都不处理。
