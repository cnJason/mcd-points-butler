# 麦麦积分管家 · mcd-points-butler

**约 500 行 Python 标准库，实现一个完整的 MCP Streamable HTTP 客户端，并附一个真实跑通的落地案例。**

> 中文 | [English](README.en.md)

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen)]()
[![MCP](https://img.shields.io/badge/MCP-Streamable%20HTTP-6E56CF)](https://modelcontextprotocol.io)

![看板截图](docs/dashboard.png)

---

## 这个项目是什么

两件事，一件技术一件业务：

1. **`McpClient`** —— 不依赖任何 SDK，只用 `urllib` 实现 MCP（Model Context Protocol）的 Streamable HTTP 传输：`initialize` 握手、`notifications/initialized`、`Mcp-Session-Id` 透传、`tools/call`、SSE 帧解析、202 空响应容错。想接 MCP 但不想拖一堆依赖的项目，可以直接抄。
2. **麦享会积分管家** —— 用上面这个客户端接麦当劳官方 MCP Server（`mcd-mcp`，35 个工具），做积分过期预警、优惠券一键领取、积分商品真实兑换。**下面的截图和输出都来自真实账号，不是 mock。**

## 案例能干什么

| 能力 | 底层 MCP Tool | 说明 |
|---|---|---|
| 积分快照 & 过期预警 | `query-my-account` | 可用/累计/将过期一目了然，超阈值亮告警条 |
| 优惠券一键领取 | `available-coupons` + `auto-bind-coupons` | 页面上点一下就入卡包，领完自动置灰 |
| 卡包校验 | `query-my-coupons` | 领完回查状态，确认真的到账 |
| 兑换推荐 | `mall-points-products` | 按可用积分过滤、按积分升序，**自动剔除已过 `downTime` 的过期商品** |
| 积分兑换 | `mall-product-detail` + `mall-create-order` | 选 SKU → 二次确认 → 真实下单，返回订单号 |
| 周报 | 上述组合 | 生成 Markdown，可接 cron / WorkBuddy 定时 |

兑换弹窗（选规格 + 使用须知 + 二次确认）：

![兑换弹窗](docs/redeem-dialog.png)

真实运行输出：

```text
== 麦享会积分快照 ==
可用积分   : 2,176.5
累计积分   : 13,568.1
本月将过期 : 159.6
[!] 预警：本月有 159.6 积分即将过期（阈值 100.0）

== 可领取优惠券 ==
- 11.9元麦辣鸡腿堡  [可领取]
- 19.9元王牌炸鸡任选2  [可领取]
- 免费脆薯饼  [可领取]
```

## 安装

零第三方依赖，Python 3.8+ 即可。

```bash
git clone https://github.com/cnJason/mcd-points-butler.git
cd mcd-points-butler

export MCD_MCP_URL="https://mcp.mcd.cn/"      # 可省略，默认即此地址
export MCD_MCP_TOKEN="<你的麦当劳 MCP token>"
```

> Token 只能通过环境变量传入。本仓库所有配置文件只含占位符，不含任何真实凭证。

## 使用

```bash
python3 mcd_butler.py serve             # Web 看板 → http://127.0.0.1:8787
python3 mcd_butler.py points            # 积分快照 + 过期预警
python3 mcd_butler.py coupons           # 查看可领券
python3 mcd_butler.py coupons --claim   # 一键领取
python3 mcd_butler.py mall              # 兑换推荐
python3 mcd_butler.py detail --spu 17073                     # 商品详情 + SKU
python3 mcd_butler.py redeem --spu 17073 --sku 17779         # 兑换预演（不扣分）
python3 mcd_butler.py redeem --spu 17073 --sku 17779 --yes   # 确认兑换（真实扣积分）
python3 mcd_butler.py report            # 生成周报
python3 mcd_butler.py all               # 一条命令跑全流程（适合定时任务）
```

看板支持深链：`http://127.0.0.1:8787/#redeem=17073` 直接打开某商品的兑换弹窗。

## 关键设计

### MCP 客户端踩过的坑（帮你省几天）

| 坑 | 现象 | 处理 |
|---|---|---|
| `notifications/initialized` 返回 202 空 body | `json.loads("")` 直接抛异常 | 空响应返回 `{}` |
| 服务器可能回 `text/event-stream` | 按 JSON 解析失败 | 按 `data:` 帧逐条解析，取最后一条 |
| `Mcp-Session-Id` 需要透传 | 部分实现不传就丢会话 | `initialize` 时捕获，后续请求带上 |
| `status=2` ≠ 在售 | 已过 `downTime` 的商品仍在列表里，点进详情才说"商品已下架" | 自己按 `downTime >= now` 过滤 |
| `auto-bind-coupons` 无券可领返回 `data: null` | `.get("data", {})` 拿到 `None` 再 `.get` 就崩 | `or {}` 兜底 |

### 兑换的三道闸门

兑换真实扣积分且不可撤销，所以：

1. **能力过滤**：只展示积分够兑、且在有效期内的商品；
2. **二次确认**：Web 必须弹窗再点确认；CLI 不加 `--yes` 只预演，打印扣分与余额；
3. **余额预检**：CLI 先比对 `points` 与 `availablePoint`，不足直接拒绝，不发请求。

### Web 架构：浏览器不碰 token

```
浏览器 (web/index.html, 零依赖单文件)
   │  fetch /api/*
   ▼
本地 Python 服务 (http.server, 127.0.0.1:8787, token 驻留进程内)
   │  tools/call
   ▼
麦当劳 MCP Server (mcd-mcp)
```

接口一览（仅监听本机）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 看板页面 |
| GET | `/api/points` | 积分快照 |
| GET | `/api/coupons` | 可领优惠券 |
| POST | `/api/coupons/claim` | 一键领券 |
| GET | `/api/my-coupons` | 卡包 |
| GET | `/api/mall?max=500` | 兑换推荐 |
| GET | `/api/mall/detail?spuId=17073` | 商品详情与 SKU |
| POST | `/api/mall/redeem` | 兑换下单 |
| GET | `/api/report` | 周报 Markdown |
| GET | `/api/health` | 健康检查 |

无后端直接打开 `web/index.html` 时自动切换内置演示数据（右上角标"演示数据"），保证没 token 也能看完整 UI。

## 目标用户

- **想接 MCP 的开发者**：需要一个零依赖、能直接读懂的 Streamable HTTP 客户端参考实现
- **麦享会会员**：积分余额不低、但总忘记兑换和领券
- **WorkBuddy 用户**：想把"别浪费积分"交给定时任务的人

## 目录结构

```
mcd-points-butler/
├── README.md / README.en.md       # 中英文说明
├── CONTEST_DECLARATION.md         # 参赛声明（原创 / 合规 / 敏感信息）
├── MCP_INTEGRATION.md             # MCP Server / Tool / 调用流程 / 业务价值
├── mcp-config.example.json        # 脱敏配置示例（仅环境变量占位符）
├── workbuddy.md                   # WorkBuddy 对话上下文
├── mcd_butler.py                  # 主程序：MCP 客户端 + CLI + Web 服务
├── web/index.html                 # 单文件看板（原生 HTML/CSS/JS）
├── docs/                          # 截图
├── reports/                       # 生成的积分周报
└── .gitignore
```
