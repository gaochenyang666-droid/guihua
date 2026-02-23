# Blueprint 拆分说明（待逐步执行）

当前 `app.py` 单文件约 3000+ 行。建议按以下结构拆分，**每次只移一个模块并跑通测试后再继续**。

## 目标结构

```
guihua.online.py/
├── app.py                 # 仅：创建 app、配置、db.init_app、注册 Blueprint、启动
├── extensions.py          # 已有：db = SQLAlchemy()
├── models/
│   └── __init__.py        # User, Post, Comment, Like, Bookmark, Notification, Tip, Report, Vote, UserVote, UsedTransaction, build_comment_tree
├── services/
│   ├── __init__.py
│   ├── web3.py            # get_working_web3, verify_transaction, try_send_tip_payout*
│   ├── arweave.py         # upload_to_arweave_native, upload_to_pinata, upload_to_arweave_with_retry
│   └── upload.py          # upload_to_imgbb, _local_upload_fallback
├── routes/
│   ├── __init__.py        # 统一 register_blueprint
│   ├── auth.py            # /api/auth/* (get_nonce, verify_signature, register, login, change_password_no_login)
│   ├── user.py            # /api/user/* (me, password, bind_wallet, revenue, withdraw)
│   ├── posts.py           # /api/posts, /api/posts/<id>, create_post, repost, vote, comments
│   ├── tips.py            # /api/tips/verify
│   ├── config.py          # /api/config/fees, /api/config/public
│   └── admin.py           # /api/admin/*
└── decorators.py          # token_required, admin_required（用 current_app.config）
```

## 依赖与顺序

1. **extensions.py**：仅 `db = SQLAlchemy()`，无 app。
2. **decorators.py**：`from flask import current_app, g, request, jsonify`；`from extensions import db`；`from models import User`；内部用 `current_app.config['SECRET_KEY']`。这样路由可 `from decorators import token_required` 而不依赖 app。
3. **models/__init__.py**：`from extensions import db`，再定义所有 Model 与 `build_comment_tree`。不在 models 里 import app。
4. **services/**：需要 config 时用 `from flask import current_app`，或由调用方传入。
5. **routes/**：各 Blueprint 内 `from extensions import db`，`from models import User, Post, ...`，`from decorators import token_required`，业务逻辑从 app.py 剪切过来。
6. **app.py**：  
   `app = Flask(__name__)` → 配置 → `from extensions import db` → `db.init_app(app)` → `from models import *`（或按需 import）→ 注册各 Blueprint → 其余启动逻辑（init_db、run）。

## 已完成的优化（本次）

- 个人页「打赏收入（可提现）/ 提现」已移除（打赏直接进作者钱包，平台不过问）。
- **SECRET_KEY**：仅从环境变量读取，缺失则抛错；已删除写入 `.secret_key` 的逻辑。
- **图片上传**：未配置 IMGBB_API_KEY 时走本地上传（`static/uploads/`），编辑器与封面图可正常显示。
- **注册**：用户名 strip、长度校验，错误文案改为中文。
- **性能**：`build_comment_tree` 内 `to_dict_node` 已提到模块级 `_comment_to_dict_node`，减少每次请求创建闭包。
- **扫码登录**：前端已实现（WalletConnect）；需在环境变量配置 `WALLETCONNECT_PROJECT_ID`，否则点击会提示「管理员未配置扫码登录」。

## 建议执行顺序

1. 先完成 **models** 迁移：把 app.py 中所有 Model 与 `build_comment_tree` 移到 `models/__init__.py`，app.py 改为 `from extensions import db` + `db.init_app(app)` + `from models import ...`，跑通全站。
2. 再拆 **decorators**：把 `token_required`、`admin_required` 移到 `decorators.py`，用 `current_app`，路由改为从 `decorators` 导入。
3. 再拆 **services**：按 web3 / arweave / upload 分文件，从 app.py 抽离并改为从 `current_app` 或参数取配置。
4. 最后按 **routes** 分模块注册 Blueprint，每移一批路由就跑一遍测试。
