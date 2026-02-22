# 上线前最后一次手动测试清单（Render 预览环境）

请按以下路径在 Render 预览环境跑通一遍，确保没有逻辑死角。

---

## 1. 核心业务路径模拟

### 1.1 注册/登录
- [ ] Web2 注册/登录：用户名密码登录，检查 JWT 是否正常发放。
- [ ] Web3 钱包登录：nonce → 签名 → verify，检查 JWT 是否正常发放。
- [ ] **Token 过期时间**：代码中为 **7 天**（`timedelta(days=7)`），非 24h。若需改为 24h，在 `app.py` 中搜索 `timedelta(days=7)` 改为 `timedelta(hours=24)`。

### 1.2 发帖流程（最重要）
- [ ] **上传图片**：发帖时上传封面/图片，检查 ImgBB 是否返回有效 URL（控制台/网络面板查看请求与响应）。
- [ ] **存入 Arweave**：发帖成功后（用户支付并提交 tx_hash），检查后端是否将内容上传 Arweave，并检查返回的 id 是否有效（可到 arweave.net 用 id 查询）。
- [ ] **支付校验**：
  - 手动向 **RECEIVE_ADDRESS** 转一笔极小额 BNB（建议 ≥ 1 USD 等值，否则会报 Insufficient fee）。
  - 使用该 tx_hash 在发帖流程中提交，检查后端 `verify_transaction` 是否通过。
  - 确认校验项：**to == RECEIVE_ADDRESS**、**value >= 发帖费**、**from == 当前登录钱包**、**tx_hash 未被使用过**、**至少 1 个区块确认**。
  - 发帖成功后检查该帖 `is_paid` 状态为 true。
- [ ] **首页显示**：打开首页，确认 `get_posts` 返回 200 且帖子列表正常显示。**说明**：本接口不请求 Arweave，内容来自 DB，因此不会因 Arweave 网关慢而导致 500。

### 1.3 其他关键路径（建议）
- [ ] 点赞、评论、收藏：各做一次，确认写入与展示正常。
- [ ] 打赏：一笔小额 BNB 打赏到作者，确认平台抽成与作者到账（若已配置 PLATFORM_PRIVATE_KEY）。

---

## 2. 数据库安全与环境变量

在 Render Dashboard → 对应 Service → **Environment** 中确认：

| 变量 | 要求 |
|------|------|
| **ALLOW_INIT_DB** | 设为 `false` 或**直接删除**。防止每次重启都插入测试“诡话”等种子数据。 |
| **RECEIVE_ADDRESS** | 你用来收款的**正式 BSC 钱包地址**（与发帖费、打赏收款一致）。 |
| **DATABASE_URL** | Render 的**生产环境 PostgreSQL** 连接串，不要用本地 SQLite 路径。 |
| **FLASK_DEBUG** | 必须为 `false`（生产环境）。 |
| **SECRET_KEY** | 已设置且足够随机，不要留空。 |

---

## 3. Web3 特性（已实现，上线后 48h 内可再验证）

- **动态 Gas**：打赏与 NFT 铸造已使用「实时 gas × 1.1，上限 20 gwei」，减少因 gas 不足导致的失败。
- **防假充值**：`verify_transaction` 已要求交易至少有 **1 个区块确认**（当前区块高度 - 交易区块高度 ≥ 1），降低链重组导致的假充值风险。若需更保守，可将确认数改为 2 或 3（在 `app.py` 中把 `latest - current_block < 1` 改为 `< 2` 或 `< 3`）。

---

## 4. 前端最后确认（index.html）

- **控制台**：已减少敏感信息的直接输出；若仍有调试用 `console.log`，上线前可全局搜索并移除或改为仅在开发环境输出。
- **错误提示**：当 `/api/posts` 因网络超时或 500 失败时，前端会显示灰色/中性提示文案和「重试」按钮，不会白屏崩溃。

---

## 5. 运营准备

### 冷启动内容
- 若希望首页「不空」，可在**首次部署前**在 Render 环境变量中临时设置 **ALLOW_INIT_DB=true**，部署一次，让 `init_db_data()` 插入种子文章与管理员账号。
- 部署成功后**立即**将 **ALLOW_INIT_DB** 删掉或设为 **false**，避免之后每次重启重复插入。

### 备份计划
- **requirements.txt**：已在仓库中，建议本地与 Git 各保留一份。
- **.env 关键配置**：在安全位置（如本地加密盘或密码管理器）保留一份离线备份，包含：
  - `SECRET_KEY`
  - `DATABASE_URL`（若自建库）
  - `RECEIVE_ADDRESS`、`PLATFORM_PRIVATE_KEY`（若使用）
  - `IMGBB_API_KEY`、Arweave 相关、Pinata 等
- 不要将 `.env` 或含私钥的文件提交到 Git。

---

## 6. 检查完成签字

- [ ] 上述 1～5 项均已核对或执行。
- [ ] 确认 Render 使用生产 PostgreSQL，且 ALLOW_INIT_DB 已关闭。
- [ ] 确认 RECEIVE_ADDRESS 为正式收款地址。

完成以上后即可视为上线前最后一次手动检查通过。
