# 打赏与提现 / 自动打款 配置说明

本文说明如何配置环境变量，以及如何启用「作者提现」与「平台自动打款」（对可提现余额 ≥10 USDT 的作者自动转账到其绑定钱包）。

---

## 一、环境变量配置

在服务器或本地的 `.env` 文件中配置以下变量（部署平台如 Render 则在 Environment 里添加）。

### 1. 必配：收款与 USDT

| 变量 | 说明 | 示例 |
|------|------|------|
| **RECEIVE_ADDRESS** | 平台收款地址（发帖费、打赏都打到这个地址） | `0xYourReceiveAddressHere` |
| **BSC_RPC_URL** | BSC 节点 RPC | `https://bsc-dataseed.binance.org/` |
| **USDT_CONTRACT_ADDRESS** | BSC 主网 USDT 合约（不填则用默认） | `0x55d398326f99059fF775485246999027B3197955` |

### 2. 提现 / 自动打款 必配

| 变量 | 说明 | 如何填写 |
|------|------|----------|
| **PLATFORM_PRIVATE_KEY** | 与 RECEIVE_ADDRESS **同一钱包**的私钥 | 在 MetaMask / 币安钱包 等中导出「私钥」，得到 64 位十六进制，可带 `0x` 前缀。**切勿泄露或提交到 Git。** |

示例（请替换成你自己的私钥）：

```bash
PLATFORM_PRIVATE_KEY=0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef
```

### 3. 平台钱包里需要有什么

- **USDT（BEP-20）**：用于给作者打款。打赏进入 RECEIVE_ADDRESS 后，作者可提现或由你自动打款，钱从该钱包转出，所以需预留一定 USDT。
- **少量 BNB**：用于支付 BSC 上的 gas，每笔转 USDT 都会消耗一点 BNB。

建议：定期检查该钱包的 USDT 和 BNB 余额，避免自动打款/作者提现失败。

---

## 二、提现规则（当前逻辑）

- 打赏：用户把 USDT 打到 **RECEIVE_ADDRESS**，平台记账，93% 计入作者「可提现余额」。
- 作者提现：在「我的主页」点「提现到绑定钱包」，将可提现余额打到**作者绑定的钱包地址**（即登录/绑定用的地址）。
- **提现最低 10 USDT**：余额或单笔提现低于 10 USDT 时无法提现，前端会提示并禁用按钮。

---

## 三、自动打款怎么做（二选一）

「自动打款」指：对**可提现余额 ≥ 10 USDT** 且**已绑定钱包**的作者，由平台主动从 RECEIVE_ADDRESS 钱包转 USDT 到其绑定钱包，并扣减其可提现余额。

任选一种方式即可。

### 方式一：用 Cron 定时执行脚本（推荐）

1. **登录部署机器**（或使用 Render / 其他平台的 Cron / 定时任务功能）。

2. **确认项目路径**，例如：
   ```bash
   cd /path/to/guihua.online.py
   ```

3. **直接执行脚本**（测试一次）：
   ```bash
   python3 scripts/process_withdrawals.py
   ```
   输出示例：`Auto withdrawals: processed=2, sent=2, failed=0`

4. **配置定时任务**（Linux/macOS 用 crontab）：
   ```bash
   crontab -e
   ```
   添加一行（每天凌晨 2 点执行，请把 `/path/to/guihua.online.py` 换成你项目实际路径）：
   ```text
   0 2 * * * cd /path/to/guihua.online.py && python3 scripts/process_withdrawals.py >> /tmp/process_withdrawals.log 2>&1
   ```
   保存后，cron 会按 schedule 自动执行。

5. **Render 等无 crontab 时**：可在其 Cron Job 或 Scheduled Job 里配置同一条命令（`cd 项目目录 && python3 scripts/process_withdrawals.py`），或改用下面的「方式二」用 HTTP 定时调用。

---

### 方式二：用管理后台接口（定时或手动调用）

1. **获取管理员 Token**  
   用管理员账号（如 siteadmin）在网站登录，浏览器里从 localStorage 取 token，或通过登录接口拿到返回的 `token`。

2. **请求自动打款接口**：
   ```bash
   curl -X POST 'https://你的域名/api/admin/process-withdrawals' \
     -H 'Content-Type: application/json' \
     -H 'Authorization: Bearer 这里填管理员token'
   ```

3. **返回示例**：
   ```json
   {
     "message": "自动打款已执行",
     "processed": 3,
     "sent": 2,
     "failed": 1,
     "min_usdt": 10
   }
   ```
   - `processed`：可提现 ≥10 USDT 且已绑钱包的用户数  
   - `sent`：成功打款数  
   - `failed`：失败或未绑钱包等

4. **定时调用**：用你熟悉的定时任务（如服务器 cron 里用 `curl`、或云函数的定时触发器）按需定期执行上述 POST 请求即可。

---

## 四、小结检查清单

- [ ] `.env` 里已配置 **RECEIVE_ADDRESS**、**PLATFORM_PRIVATE_KEY**、**USDT_CONTRACT_ADDRESS**（或不填用默认）
- [ ] 平台钱包（RECEIVE_ADDRESS 对应钱包）里有一定 USDT 和少量 BNB
- [ ] 自动打款已选一种方式并配置：**Cron 执行 `scripts/process_withdrawals.py`** 或 **定时/手动调用 `POST /api/admin/process-withdrawals`**
- [ ] 作者端：已绑定钱包，且可提现 ≥10 USDT 时才能提现或被打款

完成以上步骤后，打赏会记账到作者可提现余额，作者可手动提现到绑定钱包，你也可通过自动打款定期把余额打到作者绑定钱包。
