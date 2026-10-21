# MCP 集成说明（MCP_INTEGRATION）

本文档说明本项目实际使用的麦当劳 MCP Server、Tool 清单、完整调用流程与业务价值。

## 一、使用的 MCP Server

| 项目 | 值 |
|---|---|
| Server 名称 | `mcd-mcp`（serverInfo 实测返回 v1.0.0） |
| 接入地址 | `https://mcp.mcd.cn/` |
| 传输方式 | MCP Streamable HTTP（JSON-RPC 2.0 over HTTPS POST） |
| 鉴权方式 | `Authorization: Bearer <token>`（token 通过环境变量注入，不入库） |
| 实测握手 | `initialize` 返回 `protocolVersion: 2025-03-26`、`capabilities.tools` |

## 二、实际使用的 Tool 清单

本项目只使用**查询与领取**类工具，刻意不使用下单/兑换/抽奖类写工具（见 CONTEST_DECLARATION.md 合规性声明）：

| Tool | 类型 | 用途 | 调用位置 |
|---|---|---|---|
| `query-my-account` | 查询 | 积分账户快照：可用/累计/将过期/冻结积分 | `cmd_points` / `cmd_mall` / `cmd_report` |
| `available-coupons` | 查询 | 麦麦省当前可领取的优惠券列表 | `cmd_coupons` / `cmd_report` |
| `auto-bind-coupons` | 领取（低风险） | 一键领取全部可领券，仅在显式传 `--claim` 或点击页面按钮时调用 | `cmd_coupons --claim` / `POST /api/coupons/claim` |
| `query-my-coupons` | 查询 | 卡包内已领取券列表（校验领取结果、展示卡包张数） | `GET /api/my-coupons` |
| `mall-points-products` | 查询 | 积分商城可兑换商品列表（SPU 级） | `cmd_mall` / `cmd_report` |
| `now-time-info` | 查询 | 服务器时间（可用于过期天数计算，扩展项） | — |

未使用但了解其定位的工具：`mall-product-detail`（SPU 详情/SKU）、`mall-create-order`（兑换下单）、`query-meals` / `calculate-price` / `create-order`（点餐链路）、`query-party-*`（派对预约）等，共 35 个。

## 三、调用流程

### 3.1 通信层（`McpClient`，`mcd_butler.py`）

零依赖标准库实现的 MCP Streamable HTTP 客户端：

```
POST https://mcp.mcd.cn/
Headers:
  Content-Type: application/json
  Accept: application/json, text/event-stream
  Authorization: Bearer $MCD_MCP_TOKEN
  Mcp-Session-Id: <initialize 返回时透传，可选>
Body: {"jsonrpc":"2.0","id":1,"method":"<method>","params":{...}}
```

生命周期：

1. **initialize** → 获取 serverInfo 与 Mcp-Session-Id（若服务器下发）
2. **notifications/initialized** → 完成握手（服务器返回 202 空 body，需容错）
3. **tools/call** → 逐工具调用；优先读 `structuredContent`，降级解析 `content[].text`
4. 兼容两种响应形态：`application/json` 与 `text/event-stream`（SSE `data:` 帧解析）

### 3.2 业务流程（`all` 子命令 / WorkBuddy 定时任务）

```
initialize
   │
   ▼
query-my-account ──► 积分快照
   │                  └─ currentMouthExpirePoint ≥ 阈值 → 过期预警
   ▼
available-coupons ─► 可领券列表（--claim 时追加 auto-bind-coupons）
   │
   ▼
mall-points-products ─► 过滤 shopId=2（积分兑换餐品券）且 status=2（在售）
   │                     按所需积分升序，仅保留 ≤ 可用积分的 SPU
   ▼
汇总生成 reports/report-YYYY-MM-DD.md（Markdown 周报）
```

关键业务规则（来自实测数据结构）：

- `shopId=2` 为积分兑换餐品券（`mall-create-order` 仅支持该 shopId），`shopId=5` 为付费派对类活动，积分兑换场景应排除；
- `status=2` 表示在售可兑换；
- `point` 为所需积分，`downTime` 为兑换截止时间，商品列表共约 50 个 SPU，其中餐品券类约 23 个。

### 3.3 Web 看板链路（`serve` 子命令）

浏览器不直接访问 MCP（避免 token 暴露与 CORS 问题），采用「前端 → 本地服务 → MCP Server」三段式：

```
浏览器 (web/index.html)
   │  fetch /api/points /api/coupons /api/mall /api/report
   ▼
本地 Python 服务（http.server，仅监听 127.0.0.1:8787，token 驻留进程内）
   │  tools/call
   ▼
麦当劳 MCP Server (mcd-mcp)
```

设计要点：

- **凭证隔离**：token 只经环境变量注入本地服务进程，页面 JS 中不存在任何凭证，接口也不回传 token；
- **零前端依赖**：单文件 HTML + 原生 fetch，无 CDN、无构建步骤，离线可用；
- **降级策略**：检测不到本地服务时自动切换内置演示数据（页面右上角标记「演示数据」），保证评审在没有 token 的环境下也能看到完整 UI；
- **只读优先**：仅 `/api/coupons/claim` 一个写接口，且需前端显式点击按钮触发。

### 3.4 WorkBuddy 自动化集成

本项目在腾讯 WorkBuddy 中通过「自定义连接器」接入同一 MCP Server（配置见 `mcp-config.example.json`），并创建每日定时自动化，Prompt 等价于：

```text
运行麦麦积分管家：
1. 执行 mcd_butler.py all（MCD_MCP_TOKEN 从环境读取）；
2. 若本月将过期积分 ≥ 100，提醒我并用 mall 结果推荐最划算的兑换项；
3. 将生成的周报文件发给我。
```

WorkBuddy 对话上下文与联动说明详见 `workbuddy.md`。

## 四、真实调用示例（2026-10-21 实测）

```jsonc
// tools/call: query-my-account（响应节选，已脱敏 accountId）
{"success": true, "code": 200, "message": "请求成功",
 "data": {"availablePoint": "2176.5", "accumulativePoint": "13568.1",
          "currentMouthExpirePoint": "159.6", "frozenPoint": "0", "usedPoint": "1507"}}

// tools/call: available-coupons（响应节选）
{"data": [{"couponName": "11.9元麦辣鸡腿堡", "couponStatus": "CAN_GET", "label": "可领取"},
          {"couponName": "19.9元王牌炸鸡任选2", "couponStatus": "CAN_GET", "label": "可领取"},
          {"couponName": "免费脆薯饼", "couponStatus": "CAN_GET", "label": "可领取"}]}

// tools/call: mall-points-products（响应节选）
{"data": [{"spuName": "18.8元板烧鸡腿堡两件套", "spuId": 123, "point": "100",
           "shopId": 2, "catName": "到店专用", "status": 2, "price": "18.8"}]}
```

## 五、业务价值

1. **止损**：积分过期是"沉默损失"。以实测账户为例，累计已过期 9,884.6 分，而当前可用仅 2,176.5 分——过期预警把"月底才发现"变成"提前两周行动"。
2. **增收替代**：50 分兑 5.9 元派券、100 分兑 18.8 元板烧堡两件套，积分兑换的实际折扣率显著高于直接消费，推荐引擎按可用积分精准过滤，用户零决策成本。
3. **券利用率为 0 → 100**：可领券（如免费脆薯饼、11.9 元麦辣鸡腿堡）从"记得才领"变为每次运行自动入卡。
4. **可复用的工程价值**：单文件零依赖 MCP 客户端，可被其他参赛者或开发者直接改造复用。
