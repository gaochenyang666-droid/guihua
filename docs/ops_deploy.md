# 运维接入说明

## 1. Render 推荐部署

仓库根目录已经提供 [render.yaml](../../render.yaml)，默认包含：

1. `guihua-web`
- Web Service
- 单 worker gunicorn
- 连接 Postgres 和 Redis

2. `guihua-publish-compensation`
- Render Cron Job
- 每 3 分钟执行一轮待发布补偿

3. `guihua-db`
- Postgres

4. `guihua-redis`
- Redis

推荐：
- 直接使用 `render.yaml` 创建资源
- Web Service 上保持 `ENABLE_PUBLISH_COMPENSATION_WORKER=false`
- 由 Cron Job 负责补偿，避免多实例重复扫队列
- `REDIS_URL` 视为正式运行依赖配置项：未配置时系统仍能 fallback，但限流、钱包 nonce、浏览量防刷都会退化为进程内模式

## 2. 待发布自动补偿

项目内已经提供两种补偿方式：

1. 进程内补偿 worker
- 启动条件：`ENABLE_PUBLISH_COMPENSATION_WORKER=true`
- 补偿间隔：`PUBLISH_COMPENSATION_INTERVAL_SEC`

示例：

```bash
ENABLE_PUBLISH_COMPENSATION_WORKER=true
PUBLISH_COMPENSATION_INTERVAL_SEC=180
PUBLISH_COMPENSATION_MIN_AGE_SEC=60
```

- `PUBLISH_COMPENSATION_MIN_AGE_SEC`：待发布记录需等待至少该秒数后才参与补偿（默认 60），避免刚写入即重试。

说明：
- 单进程部署可直接开启。
- 多 worker（如 gunicorn 多进程）不建议所有 worker 都开；建议仅保留一个 worker，或关闭进程内 worker，改用定时任务。

2. 定时任务 / cron

仓库内可直接执行：

```bash
python3 scripts/run_publish_compensation.py
```

可选传处理上限：

```bash
python3 scripts/run_publish_compensation.py 20
```

适合：
- Linux `crontab`
- Render Cron Job
- Railway / Fly.io / VPS 定时任务

Linux crontab 示例（每 3 分钟执行一次）：

```cron
*/3 * * * * cd /path/to/guihua.online.py && /usr/bin/python3 scripts/run_publish_compensation.py 12 >> /var/log/guihua_compensation.log 2>&1
```

## 3. 推荐部署策略

### 单机 / 单进程

推荐：
- 开启进程内 worker
- 同时保留后台手动补偿入口

### 多进程 Web 服务

推荐：
- `ENABLE_PUBLISH_COMPENSATION_WORKER=false`
- 单独配置 cron / 定时任务执行 `scripts/run_publish_compensation.py`

这样可以避免多个 web worker 重复扫队列。

## 4. 后台入口

管理员后台现在有两处可用：

- `🚨 告警`
  - 查看最近一小时错误/警告
  - 查看最近事件
  - 按 `error / warn / 全部` 过滤

- `🧷 待发布`
  - 查看待恢复发布队列
  - 按状态 / 关键字筛选
  - 跳到用户主页 / 已存在帖子
  - 手动单条补偿
  - 批量运行一轮自动补偿

## 5. 发布前建议执行

本地或预发环境建议跑：

```bash
python3 scripts/check_release_suite.py http://127.0.0.1:5012
```

这会串行执行：
- 前端 smoke
- 管理员 smoke
- 钱包 smoke
- 发帖 smoke
- 系列/举报 smoke
- ops smoke

线上部署后验收与远程模式说明见 `docs/release_suite.md`（包含远程账号环境变量、remote-safe skip 规则与验收 checklist）。

补充：推荐在 GitHub Actions 中配置远程验收 workflow（见 `docs/release_suite.md` 的 CI / 门禁章节），用于部署后的自动验收与日志归档。

如果 workflow 文件尚未真正推上 GitHub：
- 代码和文档已经准备到“只差权限即可启用”的状态
- 需要使用带 `workflow` scope 的 PAT 或等效 GitHub 权限来推送 `.github/workflows/` 下的文件
