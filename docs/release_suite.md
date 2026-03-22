# Release Suite 上线验收体系

## 用途

Release suite 用于**发布前本地全链路自测**，以及**上线后对真实域名做验收**。

- **本地模式**：可写本地 DB、可造测试数据、可跑完整链路（含 wallet / check_tx / pending publication）。
- **远程模式**：**不直接写远程 DB**，不依赖本地构造数据，只通过真实 API 验证可远程验收的链路；对无法远程复现的项做 `skipped(remote-safe)`，不判失败。

## 本地跑法

服务已启动在 5012：

```bash
python3 scripts/check_release_suite.py http://127.0.0.1:5012
```

## 线上跑法（部署后验收）

```bash
GUIHUA_SKIP_SSL_VERIFY=1 \
GUIHUA_ADMIN_TOKEN=你的管理员token \
python3 scripts/check_release_suite.py https://guihua.fun
```

### 可选：普通用户（举报/通知等链路更贴近真实）

```bash
GUIHUA_USER_TOKEN=普通用户token
```

### 兼容旧方式（不推荐，可能触发登录限流 429）

```bash
GUIHUA_ADMIN_USERNAME=你的管理员用户名
GUIHUA_ADMIN_PASSWORD=你的密码
GUIHUA_USER_USERNAME=普通用户名
GUIHUA_USER_PASSWORD=密码
```

## 远程模式的自动 skip（remote-safe）

- **wallet_flow**：远程模式自动跳过，输出 `wallet_flow_skipped=1`。
- **check_tx / pending publication**：远程模式自动跳过（仅本地模式全链路验证）。
- **远程 suite 不直接写数据库**：不使用本地 DB 造数据去“假装”远程已有；只走真实 API。

> 远程模式主要用于**上线后验收**，不是全链路压测/容量验证的替代品。

## CI / 门禁（GitHub Actions）

仓库提供 workflow：`.github/workflows/release-suite-remote.yml`，用于远程验收与日志归档。

建议配置仓库 Secrets：

- `GUIHUA_BASE_URL`（推荐，push 到 `main` 时自动验收用）
- `GUIHUA_ADMIN_TOKEN`（必填，推荐）
- `GUIHUA_USER_TOKEN`（可选）
- `GUIHUA_SKIP_SSL_VERIFY`（可选，设为 `1` 时跳过 SSL 校验）

使用方式：

- 手动触发 `release-suite-remote`，输入 `base_url`（例如 `https://guihua.fun`）。
- 或者在仓库 Secrets 中配置 `GUIHUA_BASE_URL`，让 `push -> main` 自动跑远程验收。
- 运行结果的 stdout/stderr 会作为 artifact `release-suite-logs` 保存，便于留痕与排障。

注意：
- 当前仓库若要把 `.github/workflows/release-suite-remote.yml` 真正 push 到 GitHub，所使用的 PAT / 账号需要具备 `workflow` 权限。
- 代码侧和文档侧已经准备完成；如果远端还没有跑起来，通常只差这项 GitHub 权限或对应 secrets 未配置。

## Suite 输出与判定

`scripts/check_release_suite.py` 会打印逐项结果，并在 summary 中区分：

- **passed**
- **skipped(remote-safe)**
- **failed**

目标是让人一眼看出这次“全绿”是**真全测过**还是**远程安全跳过了部分链路**。

## 包含脚本（顺序执行）

| 脚本 | 说明 |
|------|------|
| check_frontend_smoke.py | 首页/帖子/通知/个人页/工作室页面壳与 API |
| check_browser_auth_flow.py | 注册/登录、me、退出 |
| check_admin_flow.py | 管理员相关链路（远程使用真实管理员账号） |
| check_wallet_flow.py | 钱包 nonce/签名/绑钱包（远程自动 skip） |
| check_post_flow.py | 发帖预检查与创建（远程跳过 check_tx/pending） |
| check_series_report_flow.py | 系列/举报/通知（远程用真实账号走 API） |
| check_ops_flow.py | 运维统计、Redis 状态、ops summary、补偿批次（远程不造 pending） |

## 线上验收 checklist（模板）

### 部署前

- **pull 最新代码**
- **检查 Render 环境变量**
- **确认 `REDIS_URL` 已配置**

### 部署后

- **跑 release suite**（见上面的线上跑法）
- **检查后台运维页**
  - Redis 状态
  - pending publications
  - ops summary
- **抽查关键页面**
  - 登录
  - 发帖
  - 个人页
  - 工作室

### 记录

- **记录本次 suite 结果**
  - 若有 `skipped(remote-safe)`：注明是远程安全跳过项（属于预期）。
  - 若有 `failed`：记录失败脚本与原因（含输出）。
