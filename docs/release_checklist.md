# 上线前检查清单

## 1. 代码与回归

- 确认 `main` 已推送到远端
- 确认本地编译通过

```bash
python3 -m py_compile app.py routes/*.py services/*.py utils/*.py scripts/*.py
```

- 确认本地 release suite 全绿

```bash
python3 scripts/check_release_suite.py http://127.0.0.1:5012
```

目标输出：

- `release_suite_summary=ok`
- `release_suite_ok=1`

## 2. GitHub Actions 远端验收

- 触发 `release-suite-remote`
- 确认最新 run 使用的是预期 commit
- 确认 run 结果为 `success`
- 保存 run 链接与 artifact

必备仓库 Secrets：

- `GUIHUA_BASE_URL`
- `GUIHUA_ADMIN_TOKEN` 或 `GUIHUA_ADMIN_USERNAME` + `GUIHUA_ADMIN_PASSWORD`
- `SECRET_KEY`

可选：

- `GUIHUA_USER_TOKEN`
- `GUIHUA_SKIP_SSL_VERIFY`

## 3. Render / 生产环境

- 确认 Web Service 已部署到最新 commit
- 确认 Cron Job 配置存在且正常
- 确认以下环境变量已配置：
  - `SECRET_KEY`
  - `DATABASE_URL`
  - `REDIS_URL`
  - `RECEIVE_ADDRESS`
  - `BSC_RPC_URL`
  - `AR_KEY_DATA`
  - `IMGBB_API_KEY`

## 4. Redis 生产就绪

- 在 Render 中确认 `REDIS_URL` 已实际注入
- 确认启动日志不再出现：
  - `WARNING: REDIS_URL is not set.`
- 确认远端验收中的 `check_ops_flow.py` 通过
- 确认 Redis 状态满足：
  - `status = ok`
  - `readiness = ready`
  - `degraded = false`
  - `recommendation` 不再提示生产待补齐

## 5. 人工抽查

- 首页可访问
- 故事详情页可访问
- 登录/登出可用
- 评论可加载
- 管理后台可访问
- 工作室可访问

## 6. 发布留档

- 记录本次上线 commit
- 记录最新远端 workflow run 链接
- 记录 Redis 状态结论
- 若有 `skipped(remote-safe)`，注明属于预期跳过项
