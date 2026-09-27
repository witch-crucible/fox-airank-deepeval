"""订阅费用快照：原始地址记录与统一 token 坐标系。

三个职责：

1. ``value_overview`` —— 把各档位折算到统一的「每百万 token 成本」，用于横向比较性价比；
2. ``check_source`` —— 抓取单个原始地址，判定可用性与内容指纹；
3. ``refresh_pricing_sources`` —— 批量刷新来源记录，指纹变化时才推进 snapshot_at。

坐标系约定（写进页面脚注，避免口径混淆）：

* 主坐标 ``¥ / 百万 token``，需要档位标注 ``included_tokens``；
* 副坐标 ``¥ / 美元额度``，用于只公布美元额度的档位（``included_usd_credit``）。
  美元额度与 token 之间不由本模块自行换算，避免出现无依据的折算。
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from .domain import DashboardError, utc_now

#: 快照统一折算汇率，与原条目保持一致。
USD_TO_CNY = 6.75

#: 统一坐标的单位：百万 token。
MTOK = 1_000_000

#: 分区键 → 种子/库内字段名的映射；与前端 PRICING_SECTIONS 顺序一致。
PLAN_FIELDS = (
    ("agent", "agent_plans"),
    ("coding", "coding_plans"),
    ("token", "token_plans"),
)

#: 历史字段名，供脏数据兜底读取。
LEGACY_PLAN_FIELDS = {
    "agent": ("agent_plans", "ide_plans"),
    "coding": ("coding_plans", "code_plans"),
    "token": ("token_plans",),
}

#: 判定「页面不可用」的特征串：命中即视为反爬拦截或纯 JS 渲染占位页。
BLOCK_MARKERS = (
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "cf-challenge-running",
    "enable javascript to continue",
    "attention required",
    "access denied",
    "please enable cookies",
    "unusual traffic",
)

_SOURCE_TIMEOUT = 20

#: 抓取原始地址用的请求头。
_SOURCE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": "Mozilla/5.0 model-capability-dashboard/1.0",
}

#: 单次抓取最多读取的字节数。
_SOURCE_BODY_LIMIT = 2_000_000

#: 默认 opener（遵循 HTTP(S)_PROXY 等环境变量）与其直连回退 opener。
_DEFAULT_OPENER = build_opener()
_DIRECT_OPENER = build_opener(ProxyHandler({}))


# --- 统一 token 坐标系 ---


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plans_of(item: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    for field in LEGACY_PLAN_FIELDS.get(kind, (kind + "_plans",)):
        plans = item.get(field)
        if isinstance(plans, list):
            return [plan for plan in plans if isinstance(plan, dict)]
    return []


def value_rows(pricing: Any) -> list[dict[str, Any]]:
    """把定价条目摊平成可比较的档位行，并算出两个坐标系上的成本。"""
    if not isinstance(pricing, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in pricing:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "—").strip()
        for kind, _field in PLAN_FIELDS:
            for plan in _plans_of(item, kind):
                price = _number(plan.get("price_cny_month"))
                if price is None or price <= 0:
                    continue
                tokens = _number(plan.get("included_tokens"))
                credit = _number(plan.get("included_usd_credit"))
                rows.append({
                    "tool": tool,
                    "kind": kind,
                    "plan": str(plan.get("name") or "—").strip(),
                    "price_cny_month": price,
                    "included_tokens": tokens,
                    "included_usd_credit": credit,
                    "token_basis": str(plan.get("token_basis") or "").strip(),
                    "cny_per_mtok": price * MTOK / tokens if tokens and tokens > 0 else None,
                    "cny_per_usd_credit": price / credit if credit and credit > 0 else None,
                })
    return rows


def value_overview(pricing: Any) -> dict[str, Any]:
    """按坐标系把档位分成三档，供前端直接渲染性价比排行榜。"""
    rows = value_rows(pricing)
    token_rows = [row for row in rows if row["cny_per_mtok"]]
    credit_rows = [
        row for row in rows
        if not row["cny_per_mtok"] and row["cny_per_usd_credit"]
    ]
    other_rows = [
        row for row in rows
        if not row["cny_per_mtok"] and not row["cny_per_usd_credit"]
    ]
    token_rows.sort(key=lambda row: row["cny_per_mtok"])
    credit_rows.sort(key=lambda row: row["cny_per_usd_credit"])
    cheapest = token_rows[0]["cny_per_mtok"] if token_rows else None
    for row in token_rows:
        row["relative"] = row["cny_per_mtok"] / cheapest if cheapest else None
    return {
        "usd_to_cny": USD_TO_CNY,
        "token_rows": token_rows,
        "credit_rows": credit_rows,
        "other_rows": other_rows,
        "planned": len(token_rows) + len(credit_rows),
        "total": len(rows),
    }


# --- 原始地址记录 ---


def source_records(item: dict[str, Any]) -> list[dict[str, Any]]:
    """读取条目的原始地址记录；``official_url`` 视为第一来源以保持兼容。"""
    sources = item.get("sources")
    records: list[dict[str, Any]] = []
    if isinstance(sources, list):
        records.extend(record for record in sources if isinstance(record, dict))
    official = item.get("official_url")
    if isinstance(official, str) and official.strip():
        url = official.strip()
        if not any(record.get("url") == url for record in records):
            records.insert(0, {"label": "官方定价页", "url": url})
    if not records:
        tool = str(item.get("tool") or "未命名工具").strip()
        records.append({"label": f"{tool} 定价页", "url": ""})
    return records


def pricing_sources(pricing: Any) -> list[dict[str, Any]]:
    """汇总所有工具的原始地址，供页面展示与刷新入口定位。"""
    if not isinstance(pricing, list):
        return []
    grouped: list[dict[str, Any]] = []
    for item in pricing:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "—").strip()
        records = source_records(item)
        grouped.append({
            "tool": tool,
            "snapshot_at": str(item.get("snapshot_at") or "").strip(),
            "sources": [
                {
                    "label": str(record.get("label") or record.get("url") or "来源").strip(),
                    "url": str(record.get("url") or "").strip(),
                    "snapshot_at": str(record.get("snapshot_at") or item.get("snapshot_at") or "").strip(),
                    "status": str(record.get("status") or "unknown").strip() or "unknown",
                    "last_checked_at": str(record.get("last_checked_at") or "").strip(),
                    "http_status": int(_number(record.get("http_status")) or 0),
                    "http_error": str(record.get("http_error") or "").strip()[:160],
                }
                for record in records
            ],
        })
    return grouped


def _fingerprint(body: str) -> str:
    """归一化后的正文指纹，忽略空白差异，只保留内容变化。"""
    compact = re.sub(r"\s+", " ", body or "").strip()
    return hashlib.sha256(compact.encode("utf-8", "ignore")).hexdigest()[:16]


def check_source(
    url: str,
    timeout: float = _SOURCE_TIMEOUT,
    text_fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """抓取一个原始地址，返回可用状态与内容指纹。

    状态取值：``ok``（正文可读）、``partial``（正文过短，疑似纯 JS 渲染）、
    ``blocked``（反爬 / 占位页）、``error``（抓取出错）。

    传入 ``text_fetcher`` 时复用看板统一的抓取实现（便于测试注入），否则直接 urlopen。
    """
    record: dict[str, Any] = {
        "url": url,
        "checked_at": utc_now(),
        "http_status": 0,
        "status": "error",
        "http_error": "",
        "fingerprint": "",
        "bytes": 0,
    }
    if not isinstance(url, str) or not url.strip():
        record["http_error"] = "地址为空"
        return record
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        record["http_error"] = "仅支持 HTTPS 地址"
        return record
    if text_fetcher is not None:
        try:
            body = text_fetcher(url)
        except Exception as error:  # noqa: BLE001 - 单条来源失败不应中断整批刷新
            record["http_error"] = str(error)[:200]
            return record
        # 注入的抓取实现在失败时会抛异常，走到这里即代表拿到了 2xx 正文。
        record["http_status"] = 200
        record["bytes"] = len(body or "")
        record["fingerprint"] = _fingerprint(body)
        return _classify(record, body)
    body = ""
    error_message = ""
    for opener, retryable in ((_DEFAULT_OPENER, True), (_DIRECT_OPENER, False)):
        try:
            with opener.open(Request(url, headers=_SOURCE_HEADERS, method="GET"), timeout=timeout) as response:
                record["http_status"] = int(getattr(response, "status", 200) or 200)
                body = response.read(_SOURCE_BODY_LIMIT).decode("utf-8", "ignore")
            error_message = ""
            break
        except HTTPError as error:
            # 4xx 是对方的明确应答（403 反爬、404 失效），不再回退直连。
            record["http_status"] = int(error.code)
            error_message = str(error.reason or error.code)
            if not retryable or 400 <= error.code < 500:
                break
        except Exception as error:  # noqa: BLE001 - 单个来源失败不应中断整批刷新
            error_message = str(error)[:200]
            if not retryable:
                break
    record["http_error"] = error_message[:200]
    if error_message:
        # 服务器返回了明确状态码但拿不到正文，按「反爬 / 取不到」处理。
        if record["http_status"]:
            record["status"] = "blocked"
        return record
    return _classify(record, body)


def _classify(record: dict[str, Any], body: str) -> dict[str, Any]:
    """按正文判定来源可用性。"""
    if any(marker in (body or "").casefold() for marker in BLOCK_MARKERS):
        record["status"] = "blocked"
        record["http_error"] = "命中反爬 / 占位页特征"
        return record
    record["bytes"] = len(body or "")
    record["fingerprint"] = _fingerprint(body)
    if len(re.sub(r"\s+", " ", body or "").strip()) < 200:
        record["status"] = "partial"
        record["http_error"] = "正文过短，可能是纯 JS 渲染页"
        return record
    record["status"] = "ok"
    return record


def refresh_pricing_sources(
    pricing: Any,
    fetcher: Callable[[str], str] = check_source,
    tool: str | None = None,
    expire_after_days: float = 7,
) -> dict[str, Any]:
    """就地刷新原始地址记录，返回汇总报告。

    内容指纹未变化时不推进 ``snapshot_at``，避免把「抓到了页面」误当成「价格已更新」。
    """
    if not isinstance(pricing, list):
        raise DashboardError("定价数据格式无效")
    targets = [
        item for item in pricing
        if isinstance(item, dict) and (not tool or str(item.get("tool") or "").strip().casefold() == tool.casefold())
    ]
    report = {
        "checked_at": utc_now(),
        "tool": tool or "",
        "checked": 0,
        "updated": 0,
        "blocked": 0,
        "failed": 0,
        "expired": 0,
        "entries": [],
    }
    today = report["checked_at"][:10]
    for item in targets:
        changed = False
        # 先把来源记录写回条目，否则循环内对记录的改动会落在临时字典上。
        records = source_records(item)
        item["sources"] = records
        for record in records:
            url = record.get("url") or ""
            if not url:
                continue
            result = fetcher(url)
            report["checked"] += 1
            previous = str(record.get("fingerprint") or "")
            record.update({
                "last_checked_at": result["checked_at"],
                "http_status": result["http_status"],
                "status": result["status"],
                "http_error": result["http_error"],
                "bytes": result["bytes"],
            })
            if result["fingerprint"] and result["fingerprint"] != previous:
                record["fingerprint"] = result["fingerprint"]
                record["snapshot_at"] = today
                changed = True
            if result["status"] == "blocked":
                report["blocked"] += 1
            elif result["status"] == "error":
                report["failed"] += 1
            stale = str(record.get("snapshot_at") or "")
            if stale and stale != today:
                days = _days_since(stale)
                if days is not None and days >= expire_after_days:
                    report["expired"] += 1
        if changed:
            report["updated"] += 1
            item["snapshot_at"] = today
            item["sources"] = source_records(item)
        report["entries"].append({"tool": str(item.get("tool") or "—"), "snapshot_at": str(item.get("snapshot_at") or "")})
    return report


def _days_since(date: str) -> float | None:
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", date)
    if not match:
        return None
    try:
        stamp = date_cls(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None
    return (date.today() - stamp).days
