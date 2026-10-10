# 项目使用文档（开发/部署/验收）

> 适用范围：本仓库的 Flask Web 项目（guihua.online.py），包含 Web2/Web3 登录、帖子/系列/通知/后台运维、数据库迁移与验收体系。

---

## 1. 项目总体功能概览

1. **Web 页面**
   - 首页、工作室、登录页、个人页、系列页、帖子详情、公告中心、通知中心
2. **API（JSON）核心能力**
   - 登录鉴权：`/api/auth/*`（钱包 nonce 签名 + Web2 用户名/密码）
   - 帖子：`/api/posts/*`（列表、搜索、详情、点赞/收藏/转发、评论、发帖/更新/删除）
   - 系列：`/api/series/*`（目录、详情、增删与重排）
   - 通知：`/api/notifications/*`（获取/标记已读）
   - 管理后台：`/api/admin/*`（统计、用户管理、待发布补偿队列、公告、审计日志、举报处理）
   - 其他：`/api/config/*`、`/api/upload`、`/api/reports*`、打赏校验（`/api/tips/verify`）等
3. **安全与防护**
   - XSS 防御：帖子正文使用 DOMPurify 消毒
   - CSP 收紧：`script-src` 移除 `unsafe-inline`
   - DoS/爆破防护：补齐关键接口限流
   - 钱包/密码校验：打赏前校验钱包绑定；密码修改补充最短长度校验（>= 6）
4. **性能与数据一致性**
   - 列表/详情接口尽量避免 N+1 查询（通过 eager loading / 批量统计等方式）
   - Cascade 删除策略：Post/Comment 的关联数据删除更加可靠（减少手动删库逻辑）
5. **可运维性**
   - 健康检查：`GET /health`，支持 Render 的 `healthCheckPath`
   - 数据迁移：使用 Flask-Migrate（`flask db upgrade`）
   - 线上验收：Release suite（本地 + 远程安全跳过）

---

## 2. 如何在本地运行

### 2.1 准备环境变量
至少需要：
- `SECRET_KEY`（用于 JWT；没有会直接抛错）
- `FLASK_DEBUG`（可选；建议本地调试用 `true`，生产/测试用 `false`）
- `DATABASE_URL`（可选；默认会落在项目目录 `guijing.db`）
- （可选）`REDIS_URL`（可提升限流/nonce 等的稳定性）

运行前也建议准备 `IMGBB_API_KEY`（用于图片上传）。

### 2.2 安装依赖并启动
```bash
cd /path/to/guihua.online.py
pip install -r requirements.txt

# 如需显式设置端口
PORT=5012 python3 app.py
```

---

## 3. 数据库迁移（Flask-Migrate）

### 3.1 初始化（仅首次）
```bash
flask db init
```

### 3.2 生成迁移（仅在模型变更时）
```bash
flask db migrate -m "your message"
```

### 3.3 应用迁移（上线/部署时常用）
```bash
flask db upgrade
```

如果你在本地需要显式指定应用模块：
```bash
export FLASK_APP=app
flask db upgrade
```

> Render 已在 `render.yaml` 中配置 Web Service 构建命令为：`pip install ... && flask db upgrade`，用于自动迁移。

---

## 4. 运行测试（pytest）

```bash
pip install -r requirements_dev.txt
# 或确保 requirements.txt 已包含 pytest
pytest -q
```

推荐直接验证本仓库自带的套件：
```bash
python3 -m pytest tests/ -v
```

---

## 5. 线上验收（Release Suite）

Release suite 支持：
- **本地模式**：跑完整链路（含 pending publication / wallet / check_tx 等）
- **远程模式**：只走真实域名 API，不直接写远程 DB；无法远程复现的项会输出 `skipped(remote-safe)`

### 5.1 本地跑法
```bash
python3 scripts/check_release_suite.py http://127.0.0.1:5012
```

### 5.2 线上跑法（远程验收）
```bash
GUIHUA_SKIP_SSL_VERIFY=1 \
GUIHUA_ADMIN_TOKEN=你的管理员token \
python3 scripts/check_release_suite.py https://guihua.fun
```

可选普通用户：
```bash
GUIHUA_USER_TOKEN=普通用户token
```

---

## 6. 文件与目录作用说明（快速索引）

### 6.1 主入口与扩展
- `app.py`：Flask 初始化、CSP/安全 headers 中间件、`/health`、Flask-Migrate 初始化、注册 `routes/*` 蓝图、启动时自检/补表/worker 启动逻辑。
- `extensions.py`：SQLAlchemy 的 `db` 扩展实例（供 app 和模型使用）。
- `models.py`：数据库模型与序列化（`to_dict`），定义 Post/Comment/User 等表结构、关联关系与 cascade 策略。

### 6.2 路由层（Blueprint）
- `routes/pages.py`：纯模板渲染页面（`/、/studio、/login、/profile、/series/<id>、/post/<id>、/notices、/notifications`）
- `routes/auth.py`：登录鉴权（钱包 nonce 签名、Web2 注册/登录/登出/改密码）
- `routes/user.py`：用户中心 API（me/settings/checkin/achievements/group-links/password/bind-wallet 等）
- `routes/posts.py`：帖子与互动核心 API（列表/搜索/详情/点赞/收藏/转发/投票/评论/发帖等）
- `routes/series.py`：系列目录与管理 API
- `routes/notifications.py`：通知列表与已读状态更新
- `routes/admin.py`：管理员后台与运维相关 API
- `routes/misc.py`：配置、上传、公告、举报、打赏校验等“杂项”入口

### 6.3 业务层（services）
- `services/posts_query.py`：帖子列表聚合与 fallback（尽量批量、尽量避免 N+1）
- `services/posts_logic.py`：帖子发布/校验/标签解析/提及用户解析/系列权限判断等业务逻辑
- `services/blockchain.py`：链上支付/交易校验、fee 获取、交易状态检查
- `services/storage.py`：图片/永久存储上传（如 arweave / imgbb）
- `services/publish_recovery.py`：待发布补偿队列的写入/读取/清理
- `services/pending_resume.py`：从 pending 恢复发布的核心函数（与 worker/重试共用）
- `services/runtime_state.py`：nonce、view count 防刷、pending 队列等运行时状态
- `services/observability.py`：统一记录链路事件（给 routes 方便调用）
- `services/ops_monitor.py`：运维统计汇总（ops summary、flow events 等）
- 其余 services：偏启动/补表/配置读取/worker 启动与辅助逻辑

### 6.4 安全工具
- `utils/security.py`：鉴权装饰器（`token_required` / `admin_required`）、限流 `_rate_limit`、JWT 颁发/读取、CSRF/cookie 相关、DOM/HTML 清理辅助等

### 6.5 前端资源
- `static/*`：JS/CSS/图片等静态资源
  - `static/vendor/purify.min.js`：DOMPurify
  - `static/series.js`：替代 `series.html` 内联脚本（配合 CSP 去 unsafe-inline）
- `templates/*`：服务端渲染页面模板
  - `templates/post.html`：引入 DOMPurify，帖子正文以 post.js 渲染并消毒

### 6.6 测试与验收
- `tests/*`：pytest 单元测试（覆盖 health/auth/posts/notifications/admin 等）
- `scripts/*`：Release suite（本地/远程验收）、补偿 worker、烟测脚本等
- `migrations/*`：Flask-Migrate / Alembic 迁移记录

---

## 7. 进度总结（Batch 计划）

1. **Batch 1（安全加固）**：已完成
   - 钱包/密码校验、关键端点限流、`/health`、runtime.txt 对齐
2. **Batch 2（代码质量）**：已完成
   - `datetime.utcnow` 全面替换为 timezone 方案，cascade 删除策略落地
3. **Batch 3（前端安全）**：已完成
   - DOMPurify + CSP `script-src` 去 unsafe-inline
4. **Batch 4（架构拆分）**：已完成
   - app.py 拆成 8 个 Blueprint（routes 目录）
5. **Batch 5（测试覆盖）**：已完成
   - pytest 基础设施 + 43 个单元测试全绿
6. **线上紧急修复（已完成）**
   - 修复 naive/aware datetime 比较导致的登录/帖子展示异常（现已恢复）

