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

5. **在 Render 上**：见下文的「[方式一在 Render 上一步步配置](#方式一在-render-上一步步配置)」。

---

#### 方式一在 Render 上一步步配置

Render 没有服务器 crontab，要用 **Cron Job** 这种独立服务，和你的 Web Service 用同一个仓库，按 schedule 自动跑脚本。

**第 1 步：打开 Dashboard 并新建 Cron Job**

1. 登录 [Render Dashboard](https://dashboard.render.com/)。
2. 在 **Dashboard** 里点 **New +** → 选 **Cron Job**。
3. 连接仓库：选你当前用的 **GitHub（或 GitLab/Bitbucket）** 账号下的 **guihua** 仓库（和 Web Service 同一个），分支选 **main**（或你部署用的分支）。

**第 2 步：填写 Cron Job 基本信息**

- **Name**：随便起名，例如 `guihua-auto-withdrawals`。
- **Region**：和你的 Web Service 同一区域即可（可选离用户近的）。

**第 3 步：Build 设置（安装依赖）**

- **Runtime**：选 **Python 3**（和主站一致）。
- **Build Command**：若页面有这一项，填 `pip install -r requirements.txt`（让每次跑脚本时能 import 主站依赖）；若 Render 已自动识别 Python 并安装依赖，可留空。
- Cron Job 没有「Start Command」，真正执行的是下面第 5 步的 **Command**。

**第 4 步：Schedule（执行频率）**

在 **Schedule** 里填 cron 表达式，时间一律是 **UTC**：

- 每天 **UTC 2:00**（约北京时间 10:00）：`0 2 * * *`
- 每天 **UTC 18:00**（约北京时间次日 02:00）：`0 18 * * *`
- 每 12 小时一次：`0 */12 * * *`

按你需要选一个即可。

**第 5 步：Command（每次要执行的命令）**

在 **Command** 里填（从仓库根目录执行，无需写 `cd`）：

```bash
python3 scripts/process_withdrawals.py
```

保存。

**第 6 步：环境变量（和 Web Service 一致）**

Cron Job 要连数据库、读钱包配置，必须和主站用同一套环境变量。任选一种方式即可。

**方式 A：主站已经用了 Environment Group**

1. 在 Render Dashboard 左侧点进你的 **Cron Job**（例如 `guihua-auto-withdrawals`）。
2. 左侧点 **Environment**。
3. 找到 **Linked Environment Groups** 区域，点下拉框，选中主站用的那个 **Environment Group**（名字和你主站链接的相同）。
4. 点 **Link**。链接后，该 Group 里的所有变量（如 `DATABASE_URL`、`PLATFORM_PRIVATE_KEY`、`RECEIVE_ADDRESS` 等）都会自动注入到 Cron Job，无需再逐个填。
5. 保存（选 **Save only** 或 **Save and deploy** 均可）。

**方式 B：主站是逐个填的环境变量（没有用 Group）**

1. 在 Render Dashboard 左侧点进你的 **Cron Job**。
2. 左侧点 **Environment**。
3. 在 **Environment Variables** 区域，和主站保持一致地添加变量：
   - 点 **+ Add Environment Variable**，**Key** 填变量名，**Value** 填值（与主站 Web Service 里完全一致），保存一条再添加下一条。
   - 必填的大致有：`DATABASE_URL`、`RECEIVE_ADDRESS`、`PLATFORM_PRIVATE_KEY`、`BSC_RPC_URL`；若主站还配了 `USDT_CONTRACT_ADDRESS`、`SECRET_KEY`、`FLASK_APP` 等，也一并加上。
4. 若你本机有和主站一致的 `.env` 文件，可点 **Add from .env**，把 `.env` 内容粘贴进弹窗，可批量添加（注意不要包含真实私钥到公开位置）。
5. 保存（选 **Save only** 或 **Save and deploy**）。

**如何确认主站用的是哪种？**  
打开主站 Web Service → **Environment**：若能看到 **Linked Environment Groups** 且下面已链接了一个 Group，就是方式 A；若只有 **Environment Variables** 下一行行 Key/Value，就是方式 B。

**第 7 步：创建并测试**

1. 点 **Create Cron Job**，Render 会先按你的设置 build 一次。
2. Build 成功后，在 Cron Job 页面点 **Trigger Run** 手动跑一次，看 **Logs** 里是否有：
   ```text
   Auto withdrawals: processed=x, sent=x, failed=x
   ```
3. 若报错「找不到模块」或「数据库连不上」，检查 Environment 是否和 Web Service 一致、是否有 `DATABASE_URL` 和 `PLATFORM_PRIVATE_KEY`。

**第 8 步：之后**

- 之后每次到点会自动跑，无需再操作。
- 想改时间：在 Cron Job 的 **Settings** 里改 **Schedule**。
- 想立刻再跑一次：点 **Trigger Run**。

**注意**：Render 的 Cron Job 按运行时间计费，有每月最低约 $1；脚本跑完就退出，一般几秒到几十秒，费用很低。

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
