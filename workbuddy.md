# WorkBuddy 对话上下文（workbuddy.md）

本项目参与 WorkBuddy 专项奖励。本文件记录项目开发全过程中与腾讯 WorkBuddy 智能体的真实对话上下文，以证明本项目真实使用了 WorkBuddy 智能体。

## 一、使用环境

- 客户端：腾讯 WorkBuddy 桌面版（macOS）
- 工作区：`WorkBuddy/麦当劳`
- 模式：Agent 模式（可读写文件、执行命令）
- 会话时间：2026-10-21

## 二、对话上下文时间线

### 第 1 步：接入麦当劳 MCP Server

用户向 WorkBuddy 提供服务器地址与 token，WorkBuddy 完成接入：

- 探测 `https://mcp.mcd.cn/` 确认为 Streamable HTTP 传输、Bearer 鉴权；
- `initialize` 握手成功，确认 serverInfo 为 `mcd-mcp v1.0.0`、具备 tools 能力；
- 将配置写入 WorkBuddy 的 MCP 配置文件（`~/.workbuddy/mcp.json`），注册自定义连接器 `mcd`；
- 引导用户在连接器管理页对自定义连接器执行「信任（Trust）」激活。

### 第 2 步：能力盘点

WorkBuddy 通过 `tools/list` 拉取全部 **35 个工具**并按业务归类（门店/外送、点餐、积分商城、派对/活动、优惠/抽奖、营养查询），为项目方向选型提供依据。

### 第 3 步：真实调用验证（MCP 激活前后的过渡方案）

在自定义连接器完成 Trust 之前，WorkBuddy 直接以 MCP 客户端方式（JSON-RPC over HTTPS）验证了真实调用链路：

- `now-time-info` → 服务器时间正常返回；
- `query-my-account` → 返回真实积分账户：可用 2,176.5 分，**本月将过期 159.6 分**；
- `mall-points-products` → 50 个 SPU（含 23 个积分兑换餐品券）；
- `available-coupons` → 3 张可领券（11.9 元麦辣鸡腿堡、19.9 元王牌炸鸡任选 2、免费脆薯饼）。

「本月将过期 159.6 分」这一真实数据直接催生了项目主题——**积分过期止损**。

### 第 4 步：项目选型与立项

WorkBuddy 基于真实能力盘点给出 4 个候选方向（积分管家 / 营养点餐助手 / 派对规划助手 / 薅羊毛助手），用户选定「麦麦积分管家」并确认参与 WorkBuddy 专项奖励。

### 第 5 步：WorkBuddy 驱动的项目开发（Agent 模式）

WorkBuddy 在 Agent 模式下完成了全部工程动作：

1. 建立任务清单（抓数据 → 写代码 → 验证 → 文档 → git）并逐项推进；
2. 编写零依赖的 MCP Streamable HTTP 客户端与 CLI（`mcd_butler.py`）；
3. 修复首版 bug（notification 202 空 body 导致 JSONDecodeError）后重新验证；
4. 真实跑通 `points` / `coupons` / `mall` / `report` 四个子命令并生成周报 `reports/report-2026-10-21.md`；
5. 撰写 5 个参赛文件（本文件、README、参赛声明、集成说明、脱敏配置示例），全程确保 token 不入库。

### 第 6 步：补做 Web 看板（评审可见性）

用户追问「没有做页面吗？」——WorkBuddy 此前交付的是纯 CLI，缺少可视化界面。随即在同一会话内补齐：

1. 新增 `web/index.html`：单文件看板（原生 HTML/CSS/JS，零 CDN 依赖），含积分 Hero 卡、过期告警条、优惠券列表、兑换推荐卡片、周报生成与下载；
2. 在 `mcd_butler.py` 中新增 `serve` 子命令（标准库 `http.server`），提供 `/api/points`、`/api/coupons`、`/api/mall`、`/api/report`、`/api/coupons/claim` 接口；
3. 重构 `cmd_mall` / `cmd_report` 抽出 `_mall_items` / `_affordable` / `_report_markdown`，CLI 与 Web 共用同一套业务逻辑；
4. 联调通过：页面 200（14.8KB）、真实数据 21 项可兑换、3 张券、159.6 分过期预警；
5. 定位并绕过一个工程陷阱：本机 curl 访问 `127.0.0.1` 被环境代理拦截（502 upstream connect failed），需 `--noproxy` 才通。

### 第 7 步：补齐领券功能并真实领券

用户提出「帮我补上功能，帮我领卷」——前端此前只有券列表、缺领取入口（后端接口存在但无 UI），WorkBuddy 完成两件事：

1. **真实领取**：调用 `auto-bind-coupons` 领取 3 张券（11.9 元麦辣鸡腿堡 / 19.9 元王牌炸鸡任选 2 / 免费脆薯饼），`successCount: 3, failedCount: 0`；随后用 `query-my-coupons` 校验卡包，状态变为 `HAVING_RECEIVE`（已领取）；
2. **补 UI**：券区新增「一键领取 N 张」按钮（领完自动置灰为「已全部领取」）、已领券灰标 + ✅ 图标、卡包张数展示；新增 `GET /api/my-coupons` 接口；
3. **修边界 bug**：无券可领时 `auto-bind-coupons` 返回 `data: null`，原代码 `.get("data", {})` 触发 `AttributeError`，改为 `or {}` 兜底，幂等重测返回 `0/0` 正常。

### 第 8 步：WorkBuddy 自动化（进行中/可选）

本项目计划在 WorkBuddy 中创建每日定时自动化（等价 Prompt）：

```text
运行麦麦积分管家：
1. 执行 mcd_butler.py all（MCD_MCP_TOKEN 从环境读取）；
2. 若本月将过期积分 ≥ 100，提醒我并推荐最划算的兑换项；
3. 将生成的周报发给我。
```

## 三、WorkBuddy 在本项目中的不可替代性

1. **MCP 生态打通**：WorkBuddy 原生支持自定义 MCP 连接器，地址 + token 即完成 `mcd-mcp` 接入，35 个工具即插即用；
2. **Agent 模式闭环**：从探测协议、盘点工具、真实调用验证，到写代码、修 bug、跑测试、出文档，全程在 WorkBuddy 单一会话内完成，无需切换 IDE；
3. **真实数据驱动选型**：项目主题源于 WorkBuddy 查出的真实过期积分数据，而非拍脑袋；
4. **自动化延展**：CLI 产物可直接被 WorkBuddy 定时自动化编排，形成「积分管家」的无人值守闭环。
