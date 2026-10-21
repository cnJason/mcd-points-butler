#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd-points-butler —— 麦当劳麦享会积分管家

基于麦当劳官方 MCP Server（mcd-mcp）构建的积分运营 CLI：
  - 积分快照与过期预警
  - 麦麦省优惠券一键领取
  - 积分商城可兑换商品推荐（按可用积分过滤）
  - 生成 Markdown 积分周报

仅依赖 Python 3.8+ 标准库，零第三方依赖。

用法:
  export MCD_MCP_TOKEN="你的token"
  python3 mcd_butler.py points            # 积分快照 + 过期预警
  python3 mcd_butler.py coupons           # 查看可领取优惠券
  python3 mcd_butler.py coupons --claim   # 查看并一键领取全部可领券
  python3 mcd_butler.py mall              # 按可用积分推荐可兑换商品
  python3 mcd_butler.py mall --max 500    # 只看 500 分以内的兑换项
  python3 mcd_butler.py report            # 生成完整 Markdown 周报
  python3 mcd_butler.py all               # report + 终端摘要（适合定时任务）
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

DEFAULT_MCP_URL = "https://mcp.mcd.cn/"
JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "mcd-points-butler", "version": "1.0.0"}
TIMEOUT = 30


class McpError(RuntimeError):
    pass


class McpClient:
    """极简 MCP Streamable HTTP 客户端（JSON-RPC over POST）。

    仅依赖标准库 urllib。握手 initialize 后自动透传
    Mcp-Session-Id（若服务器返回）。
    """

    def __init__(self, url: str, token: str):
        if not token:
            raise McpError(
                "缺少 token：请设置环境变量 MCD_MCP_TOKEN"
                "（或通过 --token 传入）。切勿将 token 写进代码或提交到 git。"
            )
        self.url = url
        self.token = token
        self.session_id = None
        self._next_id = 1

    # ---- 底层通信 -------------------------------------------------------
    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return {}  # 202 Accepted（如 notifications/initialized 的响应）
        except urllib.error.HTTPError as e:
            raise McpError(f"MCP HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")
        except urllib.error.URLError as e:
            raise McpError(f"MCP 连接失败: {e.reason}")

        # 服务器可能返回 application/json 或 text/event-stream
        ctype = resp.headers.get("Content-Type", "")
        if "text/event-stream" in ctype:
            return self._parse_sse(raw)
        return json.loads(raw) if raw.strip() else {}

    @staticmethod
    def _parse_sse(raw: str) -> dict:
        """解析 SSE 帧，取最后一条 data: 的 JSON。"""
        result = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk:
                    result = json.loads(chunk)
        if result is None:
            raise McpError("SSE 响应中未找到 data 帧")
        return result

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        payload = {"jsonrpc": JSONRPC_VERSION, "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._next_id += 1
        resp = self._post(payload)
        if "error" in resp:
            raise McpError(f"MCP 错误: {resp['error']}")
        return resp.get("result", {})

    # ---- MCP 语义 -------------------------------------------------------
    def initialize(self) -> dict:
        info = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        # 通知阶段（无响应）
        try:
            self._post({"jsonrpc": JSONRPC_VERSION, "method": "notifications/initialized"})
        except McpError:
            pass
        return info

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """调用工具，返回 structuredContent（含 success/message/data）。"""
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            text = ""
            for c in result.get("content", []):
                if c.get("type") == "text":
                    text += c.get("text", "")
            raise McpError(f"工具 {name} 执行失败: {text[:300]}")
        sc = result.get("structuredContent")
        if sc is None:
            # 降级：解析第一个 text content
            for c in result.get("content", []):
                if c.get("type") == "text":
                    try:
                        return json.loads(c["text"])
                    except json.JSONDecodeError:
                        return {"raw": c["text"]}
            return {}
        return sc


# ---- 业务逻辑 ------------------------------------------------------------
def fmt_points(v) -> str:
    try:
        return f"{float(v):,.1f}"
    except (TypeError, ValueError):
        return str(v)


def cmd_points(client: McpClient, warn_threshold: float = 100.0) -> dict:
    """积分快照 + 过期预警。"""
    acc = client.call_tool("query-my-account").get("data", {})
    expiring = float(acc.get("currentMouthExpirePoint") or 0)
    available = float(acc.get("availablePoint") or 0)
    print("== 麦享会积分快照 ==")
    print(f"可用积分   : {fmt_points(available)}")
    print(f"累计积分   : {fmt_points(acc.get('accumulativePoint'))}")
    print(f"已使用     : {fmt_points(acc.get('usedPoint'))}")
    print(f"冻结       : {fmt_points(acc.get('frozenPoint'))}")
    print(f"本月将过期 : {fmt_points(expiring)}")
    if expiring >= warn_threshold:
        print(f"[!] 预警：本月有 {fmt_points(expiring)} 积分即将过期（阈值 {warn_threshold}），"
              f"建议用 `mall` 子命令看看能兑换什么。")
    elif expiring > 0:
        print(f"[i] 本月有 {fmt_points(expiring)} 积分将过期，暂未达到预警阈值。")
    return acc


def cmd_coupons(client: McpClient, claim: bool = False) -> None:
    """查看（可选一键领取）麦麦省优惠券。"""
    resp = client.call_tool("available-coupons")
    coupons = resp.get("data", [])
    if not coupons:
        print("当前没有可领取的优惠券。")
        return
    print("== 可领取优惠券 ==")
    for c in coupons:
        print(f"- {c.get('couponName')}  [{c.get('label', c.get('couponStatus'))}]")
    if not claim:
        print("(使用 --claim 一键领取全部可领券)")
        return
    print("== 领取结果 ==")
    bind = client.call_tool("auto-bind-coupons")
    # auto-bind-coupons 返回结构因活动而异，原样打印关键信息
    print(json.dumps(bind, ensure_ascii=False)[:1000])


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("inf")


def _parse_time(v):
    """解析 MCP 返回的 'YYYY-MM-DD HH:MM:SS' 时间串，失败返回 None。"""
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _mall_items(client: McpClient) -> list:
    """拉取积分商城全部 SPU。"""
    resp = client.call_tool("mall-points-products")
    items = resp.get("data", resp) if isinstance(resp, dict) else resp
    if isinstance(items, dict):
        items = items.get("data", [])
    return items or []


def _affordable(items: list, max_points: float, include_expired: bool = False) -> list:
    """过滤出可用积分能兑换的在售餐品券（shopId=2），按所需积分升序。

    注意：仅凭 status=2 不够——已过 downTime 的商品仍会出现在列表里，
    但详情接口会返回「商品已下架」，因此这里必须按 downTime 过滤。
    """
    now = datetime.now()
    result = []
    for p in items:
        if p.get("shopId") != 2 or str(p.get("status")) != "2":
            continue
        if _to_float(p.get("point")) > max_points:
            continue
        down = _parse_time(p.get("downTime"))
        if not include_expired and down is not None and down < now:
            continue
        result.append(p)
    result.sort(key=lambda p: _to_float(p.get("point")))
    return result


def _strip_html(text) -> str:
    """把 MCP 返回的富文本说明转成纯文本（<br> 转换行，去标签，反转义）。"""
    import html
    import re
    if not text:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", str(text), flags=re.IGNORECASE)
    s = re.sub(r"</p>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def _product_detail(client: McpClient, spu_id) -> dict:
    """查询 SPU 详情与 SKU 列表（兑换前必须先拿 skuId 与 spuCategory）。"""
    resp = client.call_tool("mall-product-detail", {"spuId": int(spu_id)})
    if not resp.get("success"):
        raise McpError(resp.get("message") or "商品详情获取失败")
    data = resp.get("data") or {}
    skus = [
        {
            "skuId": s.get("skuId"),
            "points": s.get("points"),
            "price": s.get("price"),
            "extTradePrice": s.get("extTradePrice"),
        }
        for s in (data.get("skuList") or [])
    ]
    return {
        "spuId": data.get("spuId"),
        "spuName": data.get("spuName"),
        "spuCategory": str(data.get("spuCategory")),
        "shopId": data.get("shopId"),
        "downDate": data.get("downDate"),
        "note": _strip_html(data.get("note")),
        "detail": _strip_html(data.get("detail")),
        "spuLimit": data.get("spuLimit"),
        "skus": skus,
    }


def _redeem(client: McpClient, sku_id, spu_category, count: int = 1,
            address_id: str | None = None) -> dict:
    """创建积分兑换订单（写操作：真实扣积分）。

    spuCategory: "1" 虚拟商品（券），"2" 实体物品（需 addressId）。
    """
    args = {"skuId": int(sku_id), "spuCategory": str(spu_category), "count": int(count)}
    if address_id:
        args["addressId"] = address_id
    resp = client.call_tool("mall-create-order", args)
    if not resp.get("success"):
        raise McpError(resp.get("message") or "兑换失败")
    data = resp.get("data") or {}
    return {
        "orderId": data.get("orderId"),
        "amount": data.get("amount"),
        "points": data.get("points") or data.get("usePoint") or data.get("totalPoint"),
        "raw": data,
    }


def cmd_mall(client: McpClient, max_points: float | None = None, top: int = 10) -> None:
    """积分商城推荐：只看可兑换餐品券（shopId=2），按积分升序。"""
    if max_points is None:
        acc = client.call_tool("query-my-account").get("data", {})
        max_points = float(acc.get("availablePoint") or 0)
    affordable = _affordable(_mall_items(client), max_points)
    print(f"== 积分商城推荐（{fmt_points(max_points)} 分以内，按所需积分升序）==")
    for p in affordable[:top]:
        print(f"- [{fmt_points(p.get('point'))}分] {p['spuName']}  "
              f"(原价¥{p.get('price')}, 兑换至 {str(p.get('downTime'))[:10]})")
    if not affordable:
        print("可用积分暂不足以兑换任何商品，赚分要紧！")


def cmd_detail(client: McpClient, spu_id: int) -> dict:
    """查看兑换商品详情与 SKU。"""
    d = _product_detail(client, spu_id)
    print(f"== {d['spuName']} （spuId={d['spuId']}, spuCategory={d['spuCategory']}）==")
    print(f"兑换截止: {str(d.get('downDate'))[:10]}")
    if d.get("detail"):
        print(f"详情: {d['detail'][:200]}")
    print("SKU:")
    for s in d["skus"]:
        print(f"  - skuId={s['skuId']}  需 {fmt_points(s.get('points'))} 分  "
              f"现金 ¥{s.get('price')}")
    print("(兑换命令: python3 mcd_butler.py redeem --spu %s --sku <skuId> --yes)" % d["spuId"])
    return d


def cmd_redeem(client: McpClient, spu_id: int, sku_id: int | None = None,
               count: int = 1, yes: bool = False) -> None:
    """兑换积分商品（写操作，真实扣积分）。"""
    d = _product_detail(client, spu_id)
    if sku_id is None:
        print(f"== {d['spuName']} 可选 SKU ==")
        for s in d["skus"]:
            print(f"  - skuId={s['skuId']}  需 {fmt_points(s.get('points'))} 分")
        print("请用 --sku <skuId> 指定规格后重试。")
        return
    sku = next((s for s in d["skus"] if str(s["skuId"]) == str(sku_id)), None)
    if sku is None:
        raise McpError(f"spuId={spu_id} 下不存在 skuId={sku_id}")
    acc = client.call_tool("query-my-account").get("data", {})
    available = float(acc.get("availablePoint") or 0)
    need = _to_float(sku.get("points"))
    if need > available:
        raise McpError(f"积分不足：需 {fmt_points(need)}，可用 {fmt_points(available)}")
    if not yes:
        print(f"[预演] 将兑换「{d['spuName']}」skuId={sku_id}，扣 {fmt_points(need)} 积分，"
              f"兑换后余额约 {fmt_points(available - need)}。")
        print("确认执行请加 --yes（该操作真实扣积分，不可撤销）。")
        return
    r = _redeem(client, sku_id, d["spuCategory"], count)
    print("== 兑换成功 ==")
    print(f"订单号: {r.get('orderId')}")
    print(f"扣减积分: {fmt_points(need)}，剩余约 {fmt_points(available - need)}")
    if r.get("amount") not in (None, "", "0"):
        print(f"现金支付: ¥{r.get('amount')}")


def _report_markdown(client: McpClient) -> str:
    """构建 Markdown 积分周报文本。"""
    acc = client.call_tool("query-my-account").get("data", {})
    available = float(acc.get("availablePoint") or 0)
    expiring = float(acc.get("currentMouthExpirePoint") or 0)

    coupons = client.call_tool("available-coupons").get("data", [])
    affordable = _affordable(_mall_items(client), available)

    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# 麦麦积分管家周报 · {today}",
        "",
        "## 积分快照",
        "",
        "| 项目 | 数值 |",
        "|---|---|",
        f"| 可用积分 | {fmt_points(acc.get('availablePoint'))} |",
        f"| 累计积分 | {fmt_points(acc.get('accumulativePoint'))} |",
        f"| 已使用 | {fmt_points(acc.get('usedPoint'))} |",
        f"| 本月将过期 | {fmt_points(expiring)} |",
        "",
    ]
    if expiring > 0:
        lines += [f"> ⚠️ 本月有 **{fmt_points(expiring)}** 积分即将过期，建议尽快兑换。", ""]
    lines += ["## 当前可领取优惠券", ""]
    if coupons:
        for c in coupons:
            lines.append(f"- {c.get('couponName')}  [{c.get('label', c.get('couponStatus'))}]")
    else:
        lines.append("- 无")
    lines += ["", f"## 兑换推荐（{fmt_points(available)} 分以内 Top {min(10, len(affordable))}）", ""]
    if affordable:
        lines += ["| 所需积分 | 商品 | 原价 | 兑换截止 |", "|---|---|---|---|"]
        for p in affordable[:10]:
            lines.append(f"| {fmt_points(p.get('point'))} | {p['spuName']} "
                         f"| ¥{p.get('price')} | {str(p.get('downTime'))[:10]} |")
    else:
        lines.append("可用积分暂不足以兑换任何商品。")
    return "\n".join(lines) + "\n"


def cmd_report(client: McpClient, out_dir: str = "reports") -> str:
    """生成 Markdown 积分周报并落盘。"""
    report = _report_markdown(client)
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"report-{today}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"周报已生成: {path}")
    return path


def cmd_serve(client: McpClient, host: str = "127.0.0.1", port: int = 8787) -> None:
    """启动 Web 看板（标准库 HTTP 服务，前端在 web/index.html）。"""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse

    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

    class Handler(BaseHTTPRequestHandler):
        server_version = "mcd-butler/1.0"

        def log_message(self, fmt, *args):  # 静音访问日志
            pass

        def _send(self, code: int, body, ctype: str = "application/json; charset=utf-8"):
            raw = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False))

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html"):
                try:
                    with open(os.path.join(web_dir, "index.html"), "rb") as f:
                        self._send(200, f.read(), "text/html; charset=utf-8")
                except FileNotFoundError:
                    self._send(500, "web/index.html 缺失", "text/plain; charset=utf-8")
                return
            try:
                if path == "/api/points":
                    self._json(client.call_tool("query-my-account"))
                elif path == "/api/coupons":
                    self._json(client.call_tool("available-coupons"))
                elif path == "/api/my-coupons":
                    resp = client.call_tool("query-my-coupons").get("data", {})
                    coupons = resp.get("coupons", []) if isinstance(resp, dict) else []
                    self._json({"count": len(coupons), "data": coupons})
                elif path == "/api/mall":
                    qs = parse_qs(parsed.query)
                    limit = float(qs["max"][0]) if "max" in qs else None
                    if limit is None:
                        acc = client.call_tool("query-my-account").get("data", {})
                        limit = float(acc.get("availablePoint") or 0)
                    self._json({"data": _affordable(_mall_items(client), limit)})
                elif path == "/api/mall/detail":
                    qs = parse_qs(parsed.query)
                    spu_id = qs.get("spuId", [None])[0]
                    if not spu_id:
                        self._json({"error": "缺少 spuId"}, 400)
                    else:
                        self._json(_product_detail(client, spu_id))
                elif path == "/api/report":
                    self._json({"markdown": _report_markdown(client),
                                "date": datetime.now().strftime("%Y-%m-%d")})
                elif path == "/api/health":
                    self._json({"ok": True, "mode": "live"})
                else:
                    self._json({"error": "接口不存在"}, 404)
            except McpError as e:
                self._json({"error": str(e)}, 502)
            except Exception as e:  # noqa: BLE001 - 单请求失败不应拖垮服务
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def _body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                return json.loads(raw or "{}")
            except (ValueError, json.JSONDecodeError):
                return {}

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/coupons/claim":
                    # 无可领券时服务器返回 data: null，用 or {} 兜底
                    resp = client.call_tool("auto-bind-coupons").get("data") or {}
                    self._json({
                        "successCount": resp.get("successCount", 0),
                        "failedCount": resp.get("failedCount", 0),
                        "successCoupons": resp.get("successCoupons", []),
                        "failedCoupons": resp.get("failedCoupons", []),
                    })
                elif path == "/api/mall/redeem":
                    body = self._body()
                    if not body.get("skuId") or not body.get("spuCategory"):
                        self._json({"error": "缺少 skuId 或 spuCategory"}, 400)
                    else:
                        self._json(_redeem(
                            client,
                            body["skuId"],
                            body["spuCategory"],
                            int(body.get("count") or 1),
                            body.get("addressId"),
                        ))
                else:
                    self._json({"error": "接口不存在"}, 404)
            except McpError as e:
                self._json({"error": str(e)}, 502)
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"[i] 积分管家看板已启动: http://{host}:{port}", file=sys.stderr)
    print("[i] 按 Ctrl+C 停止", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[i] 已停止", file=sys.stderr)
    finally:
        httpd.server_close()


def build_client(args) -> McpClient:
    url = getattr(args, "url", None) or os.environ.get("MCD_MCP_URL", DEFAULT_MCP_URL)
    token = getattr(args, "token", None) or os.environ.get("MCD_MCP_TOKEN", "")
    client = McpClient(url, token)
    info = client.initialize()
    server = info.get("serverInfo", {})
    print(f"[i] 已连接 MCP Server: {server.get('name')} v{server.get('version')}",
          file=sys.stderr)
    return client


def main():
    parser = argparse.ArgumentParser(description="麦当劳麦享会积分管家（基于麦当劳 MCP）")
    parser.add_argument("--url", help=f"MCP Server 地址，默认 {DEFAULT_MCP_URL}，"
                                      "或环境变量 MCD_MCP_URL")
    parser.add_argument("--token", help="MCP token，或环境变量 MCD_MCP_TOKEN（推荐）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_points = sub.add_parser("points", help="积分快照 + 过期预警")
    p_points.add_argument("--warn", type=float, default=100.0, help="过期预警阈值（默认 100 分）")

    p_coupons = sub.add_parser("coupons", help="查看/领取麦麦省优惠券")
    p_coupons.add_argument("--claim", action="store_true", help="一键领取全部可领券")

    p_mall = sub.add_parser("mall", help="积分商城兑换推荐")
    p_mall.add_argument("--max", type=float, help="积分上限（默认取当前可用积分）")
    p_mall.add_argument("--top", type=int, default=10, help="展示条数（默认 10）")

    p_detail = sub.add_parser("detail", help="查看兑换商品详情与 SKU")
    p_detail.add_argument("--spu", type=int, required=True, help="商品 SPU ID")

    p_redeem = sub.add_parser("redeem", help="兑换积分商品（写操作，需 --yes 确认）")
    p_redeem.add_argument("--spu", type=int, required=True, help="商品 SPU ID")
    p_redeem.add_argument("--sku", type=int, help="SKU ID（不传则列出可选 SKU）")
    p_redeem.add_argument("--count", type=int, default=1, help="兑换数量（默认 1）")
    p_redeem.add_argument("--yes", action="store_true", help="确认执行，真实扣积分不可撤销")

    sub.add_parser("report", help="生成 Markdown 积分周报")
    sub.add_parser("all", help="report + 终端摘要（适合 cron / WorkBuddy 自动化）")

    p_serve = sub.add_parser("serve", help="启动 Web 看板（默认 http://127.0.0.1:8787）")
    p_serve.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    p_serve.add_argument("--port", type=int, default=8787, help="监听端口（默认 8787）")

    args = parser.parse_args()
    try:
        client = build_client(args)
        if args.command == "points":
            cmd_points(client, args.warn)
        elif args.command == "coupons":
            cmd_coupons(client, args.claim)
        elif args.command == "mall":
            cmd_mall(client, args.max, args.top)
        elif args.command == "detail":
            cmd_detail(client, args.spu)
        elif args.command == "redeem":
            cmd_redeem(client, args.spu, args.sku, args.count, args.yes)
        elif args.command == "report":
            cmd_report(client)
        elif args.command == "serve":
            cmd_serve(client, args.host, args.port)
        elif args.command == "all":
            cmd_points(client)
            print()
            cmd_coupons(client)
            print()
            cmd_mall(client)
            print()
            cmd_report(client)
    except McpError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
