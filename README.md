# 诡话 (GuiHua)

诡话是一个基于 Flask 的 Web3 灵异故事与都市传说内容社区。用户可以用钱包或用户名密码登录，付费发布帖子并把正文永久归档到 Arweave，读者可以点赞、评论、收藏、打赏，作者能直接收到 USDT 打赏。

## 功能概览

### 内容与互动

- 帖子发布、编辑、删除，支持正文多图与 HTML 消毒
- 评论、回复、点赞、收藏、转发
- 系列（连载）目录与文章管理
- 通知中心与公告中心

### 用户体系

- 用户等级、经验值、每日签到、成就徽章

### 身份与鉴权

- Web2 用户名密码注册登录，JWT 鉴权
- Web3 钱包登录，基于 nonce 签名校验，支持 WalletConnect 扫码
- 钱包绑定与解绑

### 支付与经济

- BSC 主网 USDT (BEP-20) 发帖费校验
- 打赏直接转入作者钱包
- 交易上链校验与重复支付防护

### 永久存储与图片

- 帖子正文经 Arweave 永久归档，失败可重试，并带补偿队列
- 图片上传使用 ImgBB

### 后台与运维

- 管理后台：数据统计、用户管理、公告、举报处理、审计日志、待发布补偿队列
- 健康检查 `GET /health`
- 待发布补偿 worker
- 服务端渲染的 SEO 页面（首页、故事列表、故事详情）

## 技术栈

- Web 框架：Flask 2.3
- ORM 与迁移：Flask-SQLAlchemy、Flask-Migrate (Alembic)
- 数据库：PostgreSQL（生产）或 SQLite（本地）
- 缓存与限流：Redis
- 区块链：web3.py 6、eth-account，对接 BSC 主网
- 永久存储：arweave-python-client
- 鉴权：PyJWT
- 内容安全：bleach、DOMPurify
- 测试：pytest
- 部署：Render（`render.yaml`）、gunicorn

## 快速开始

### 1. 准备环境变量

在项目根目录创建 `.env`，可参考 `.env.example`。常用变量如下：

- `SECRET_KEY`：JWT 签名密钥，必填
- `DATABASE_URL`：数据库连接串，本地可用 `sqlite:///guijing.db`
- `RECEIVE_ADDRESS`：BSC 主网收款地址
- `BSC_RPC_URL`：BSC RPC 节点
- `IMGBB_API_KEY`：图片上传
- `AR_KEY_FILE` 或 `AR_KEY_DATA`：Arweave 钱包密钥
- `REDIS_URL`：可选，用于限流与运行时状态
- `WALLETCONNECT_PROJECT_ID`：可选，启用钱包扫码登录

`FLASK_DEBUG` 为 `false` 时 CORS 默认关闭，如需跨域请设置 `CORS_ORIGINS`。

### 2. 安装与运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 可选：应用数据库迁移
flask db upgrade

PORT=5012 python3 app.py
```

### 3. 运行测试

```bash
pip install -r requirements_dev.txt
python3 -m pytest tests/ -v
```

## 目录结构

```text
app.py                Flask 入口、安全中间件、蓝图注册、启动自检
models.py             数据模型与序列化
extensions.py         SQLAlchemy 实例
routes/               路由蓝图（pages/auth/user/posts/series/notifications/admin/misc）
services/             业务逻辑（查询、发布、支付、存储、补偿、监控等）
utils/security.py     鉴权装饰器、限流、JWT、内容清理
templates/            服务端渲染模板
static/               前端资源（JS/CSS/vendor）
migrations/           Alembic 迁移
scripts/              烟测、验收、补偿 worker
tests/                pytest 单元测试
docs/                 设计与运维文档
```

## 部署

仓库内置 `render.yaml`，可以直接部署到 Render：

- Web Service：构建命令 `pip install -r requirements.txt && flask db upgrade`，启动命令 `gunicorn app:app`
- Cron Job：每 3 分钟运行一次待发布补偿
- 需要在 Render 控制台自行配置 `SECRET_KEY`、`DATABASE_URL`、`RECEIVE_ADDRESS`、`IMGBB_API_KEY`、`AR_KEY_DATA` 等环境变量

## 安全说明

- 所有密钥与私钥只通过环境变量注入，仓库中不保存任何明文密钥
- `.env`、`.secret_key`、`ar_key.json`、`*.db` 均已被 `.gitignore` 忽略
- 公开或共享仓库前，请确认没有提交任何真实凭据

## 相关文档

- `docs/APP_USAGE.md`：功能、运行与验收的完整说明
- `docs/ops_deploy.md`：运维与部署
- `SECURITY.md`：安全设计与审计回应
- `PRE_LAUNCH_CHECKLIST.md`：上线前检查清单
