# 麦麦积分管家 (mcd-points-butler)

基于**麦当劳官方 MCP Server（mcd-mcp）**与**腾讯 WorkBuddy 智能体**构建的麦享会积分运营助手。

一句话：**让每一分麦当劳积分都不白白过期。**

## 项目介绍

麦当劳 App 的麦享会积分经常在月底悄悄过期，优惠券也要手动去领——大多数人根本记不住。本项目通过麦当劳 MCP 的真实会员能力，把「查积分 → 领券 → 挑兑换 → 出报告」整条链路自动化：

| 能力 | 背后的 MCP Tool | 说明 |
|---|---|---|
| 积分快照 & 过期预警 | `query-my-account` | 可用/累计/将过期积分一目了然，超过阈值主动告警 |
| 优惠券一键领取 | `available-coupons` + `auto-bind-coupons` | 查询麦麦省全部可领券并自动领取 |
| 兑换推荐 | `mall-points-products` | 过滤出可积分兑换的餐品券，按所需积分升序，只用当前可用积分能兑的；已过 `downTime` 的商品自动剔除 |
| **积分兑换** | `mall-product-detail` + `mall-create-order` | 点「兑换」→ 选 SKU → 二次确认 → 真实下单，返回订单号；CLI 端不加 `--yes` 只预演不扣分 |
| 积分周报 | 上述工具组合 | 生成 Markdown 周报，可配合 cron / WorkBuddy 自动化定时运行 |
| **Web 看板** | 上述工具组合 | 一条命令启动本地看板，积分/券/兑换推荐实时可视化，支持生成与下载周报 |

真实运行示例（2026-10-21，脱敏前实际输出）：

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

== 积分商城推荐（2,176.5 分以内）==
- [50.0分] 5.9元香芋派/菠萝派任选
- [100.0分] 18.8元板烧鸡腿堡两件套
- [200.0分] 18.8元2份麦辣鸡翅
```

## 安装方法

零第三方依赖，只需要 Python 3.8+。

```bash
git clone https://github.com/<your-github-id>/mcd-points-butler.git
cd mcd-points-butler

# 配置凭证（环境变量，切勿硬编码进代码）
export MCD_MCP_URL="https://mcp.mcd.cn/"      # 可省略，默认即此地址
export MCD_MCP_TOKEN="<你的麦当劳 MCP token>"
```

> Token 获取方式以大赛主办方发放的接入指引为准。本仓库所有配置文件只含环境变量占位符，不含任何真实凭证。

## 使用示例

```bash
python3 mcd_butler.py serve             # 启动 Web 看板 → http://127.0.0.1:8787
python3 mcd_butler.py points            # 积分快照 + 过期预警
python3 mcd_butler.py coupons           # 查看可领取优惠券
python3 mcd_butler.py coupons --claim   # 一键领取全部可领券
python3 mcd_butler.py mall              # 按可用积分推荐可兑换商品
python3 mcd_butler.py mall --max 500    # 只看 500 分以内的兑换项
python3 mcd_butler.py detail --spu 17073          # 查看商品详情与 SKU
python3 mcd_butler.py redeem --spu 17073 --sku 17779          # 兑换预演（不扣分）
python3 mcd_butler.py redeem --spu 17073 --sku 17779 --yes    # 确认兑换（真实扣积分）
python3 mcd_butler.py report            # 生成 Markdown 周报到 reports/
python3 mcd_butler.py all               # report + 终端摘要（适合定时任务）
```

配合 WorkBuddy 自动化（每日 09:30 运行）的定时任务示例见 `MCP_INTEGRATION.md`。

### Web 看板

```bash
export MCD_MCP_TOKEN="<你的 token>"
python3 mcd_butler.py serve --port 8787
# 浏览器打开 http://127.0.0.1:8787
```

看板特性：

- **积分 Hero 卡**：可用积分大字展示，本月将过期积分 ≥100 时自动亮起告警条
- **优惠券列表**：实时拉取麦麦省可领券；已领取的显示灰标「已领取」并标注已入卡包
- **一键领取**：页面上直接领全部可领券，按钮显示待领张数，领完自动置灰并提示成功数；无券可领时幂等返回 0，不报错
- **卡包统计**：券区标题旁显示「卡包 N 张」
- **兑换推荐**：按可用积分过滤，50/100 分档位绿色高亮，标明原价与兑换截止日；已过期商品自动剔除
- **积分兑换**：每张商品卡带「兑换」按钮 → 弹窗展示 SKU 与使用须知 → 二次确认后真实下单，成功页显示订单号
- **周报**：一键生成 Markdown 预览 + 下载 `.md`，可存档或贴到笔记里
- **降级保护**：直接双击打开 `web/index.html`（无后端）时自动切换演示数据，适合评审快速预览 UI
- **凭证隔离**：token 只存在于本地 Python 服务进程，前端代码与网络请求中不出现任何凭证

接口一览（标准库 `http.server` 实现，仅监听 `127.0.0.1`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 看板页面 |
| GET | `/api/points` | 积分快照 |
| GET | `/api/coupons` | 可领优惠券 |
| POST | `/api/coupons/claim` | 一键领券（调用 `auto-bind-coupons`，返回 successCount/failedCount） |
| GET | `/api/my-coupons` | 卡包券列表与张数（`query-my-coupons`） |
| GET | `/api/mall?max=500` | 兑换推荐（可按积分上限过滤，自动排除已过期） |
| GET | `/api/mall/detail?spuId=17073` | 商品详情与 SKU 列表 |
| POST | `/api/mall/redeem` | 兑换下单 `{skuId, spuCategory, count}`（真实扣积分） |
| GET | `/api/report` | 生成周报 Markdown |
| GET | `/api/health` | 健康检查 |

## 目标用户

- **麦享会积分会员**：积分余额不低、但总是忘记兑换和领券的人
- **WorkBuddy 用户**：希望把"提醒我别浪费积分"这种小事交给智能体定时跑的人
- **MCP 开发者**：想要一个零依赖、可直接阅读的 MCP Streamable HTTP 客户端参考实现（`mcd_butler.py` 单文件约 350 行，纯标准库）

## 目录结构

```
mcd-points-butler/
├── README.md                  # 本文件
├── CONTEST_DECLARATION.md     # 参赛声明（原创性 / 合规性 / 敏感信息）
├── MCP_INTEGRATION.md         # MCP Server / Tool / 调用流程 / 业务价值
├── mcp-config.example.json    # 脱敏后的 MCP 配置示例（仅环境变量占位符）
├── workbuddy.md               # WorkBuddy 对话上下文（WorkBuddy 专项奖励）
├── mcd_butler.py              # 主程序：MCP 客户端 + CLI 子命令 + Web 服务
├── web/
│   └── index.html             # 单文件看板（原生 HTML/CSS/JS，零前端依赖）
├── reports/                   # 生成的积分周报（Markdown）
└── .gitignore
```
