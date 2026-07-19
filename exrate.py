#!/usr/bin/env python3
"""
汇率查询程序
从 smbs.biz（韩元牌价）和 chinamoney.com.cn（人民币中间价）获取汇率，
支持指定日期、表格/JSON 输出、推送到外部 API。
"""

import urllib.request
import urllib.parse
import urllib.error
from datetime import date, datetime
import json
import re
import sys
import time
from pathlib import Path

# ── 配置 ────────────────────────────────────────────
SMBS_URL = "http://www.smbs.biz/Flash/TodayExRate_flash.jsp?tr_date={date}"
CHINAMONEY_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"

CURRENCY_MAP = {"CNH": "CNY"}

MAX_RETRIES = 5
RETRY_DELAY = 60
BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
LOG_DIR = BASE_DIR / "logs"
CONFIG_FILE = BASE_DIR / "config.json"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


# ── 通用工具 ────────────────────────────────────────


def log_failure(url, attempts, last_err, source_name=""):
    """将失败信息写入日志文件"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tag = date.today().strftime("%Y%m%d")
    log_file = LOG_DIR / f"exrate_error_{tag}.log"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(
            f"[{ts}] {source_name} 获取失败\n"
            f"  请求URL: {url}\n"
            f"  重试次数: {attempts}\n"
            f"  最后错误: {last_err}\n"
            f"{'-' * 60}\n"
        )
    print(f"[错误] {source_name} 失败详情已写入日志: {log_file}", file=sys.stderr)


def fetch_with_retry(url, source_name="", decode="utf-8", is_json=False,
                     check_ok=lambda b: True):
    """
    通用带重试的 HTTP GET。
    is_json=True 时 response 先 JSON 反序列化再传给 check_ok。
    成功返回解析后的对象（str 或 dict/list），失败返回 None。
    """
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
            text = body.decode(decode)
            obj = json.loads(text) if is_json else text

            if check_ok(obj):
                return obj
            last_err = "返回内容异常，未通过有效性检查"

        except (urllib.error.URLError, TimeoutError, UnicodeError,
                json.JSONDecodeError) as e:
            last_err = str(e)

        retry_message = (
            f"，{RETRY_DELAY}秒后重试..." if attempt < MAX_RETRIES else ""
        )
        print(f"[{source_name}][第{attempt}次] 请求失败: "
              f"{last_err}{retry_message}", file=sys.stderr)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    log_failure(url, MAX_RETRIES, last_err, source_name)
    return None


# ── smbs.biz ────────────────────────────────────────


def fetch_smbs(date_obj=None):
    """获取 smbs 韩元牌价，成功返回原始字符串，失败返回 None"""
    if date_obj is None:
        date_obj = date.today()
    url = SMBS_URL.format(date=date_obj.strftime("%Y-%m-%d"))
    return fetch_with_retry(url, "smbs", "EUC-KR",
                            check_ok=lambda t: t.strip().startswith("?") and "loading=ok" in t)


def parse_smbs(raw):
    """解析 smbs 返回的 query-string → 结构化列表"""
    text = raw.lstrip()
    if text.startswith("?"):
        text = text[1:]
    params = urllib.parse.parse_qs(text)

    results = []
    for key, vals in params.items():
        if not re.fullmatch(r"[A-Z]{3}", key):
            continue
        try:
            rate = round(float(vals[0].replace(",", "")), 8)
        except (IndexError, ValueError):
            continue
        results.append({
            "from_currency": CURRENCY_MAP.get(key, key),
            "to_currency": "KRW",
            "rate": rate,
        })
    return results


# ── chinamoney ──────────────────────────────────────


def parse_chinamoney_pair(pair):
    """解析货币对，返回 (from_currency, to_currency, multiplier)"""
    parts = pair.split("/")
    if len(parts) != 2:
        return None, None, None
    left, right = parts
    mult = 1
    if left.startswith("100"):
        left = left[3:]
        mult = 100
    return left, right, mult


def fetch_chinamoney(date_obj=None):
    """
    获取中国外汇交易中心中间价。
    date_obj 指定日期时 API 会加上查询参数。
    成功返回结构化 dict，失败返回 None。
    """
    url = CHINAMONEY_URL
    if date_obj is not None:
        ds = date_obj.strftime("%Y-%m-%d")
        url += f"?startDate={ds}&endDate={ds}"

    data = fetch_with_retry(
        url, "chinamoney", is_json=True,
        check_ok=lambda d: (
            isinstance(d, dict)
            and isinstance(d.get("records"), list)
            and isinstance(d.get("data"), dict)
            and isinstance(d["data"].get("head"), list)
        ),
    )
    if data is None:
        return None

    records = data.get("records", [])
    if not records:
        print("[提示] chinamoney 无可用数据（可能非交易日）", file=sys.stderr)
        return None

    # 找到指定日期的记录
    if date_obj is not None:
        ds = date_obj.strftime("%Y-%m-%d")
        record = next(
            (r for r in records if isinstance(r, dict) and r.get("date") == ds),
            None,
        )
        if record is None:
            print(f"[提示] chinamoney 无 {ds} 的数据（可能非交易日），跳过", file=sys.stderr)
            return None
    else:
        record = records[0]
        if not isinstance(record, dict):
            return None

    head = data["data"]["head"]
    values = record.get("values", [])

    results = []
    for pair, val_str in zip(head, values):
        frm, to, mult = parse_chinamoney_pair(pair)
        if frm is None:
            continue
        try:
            rate = float(val_str) / mult
        except (TypeError, ValueError):
            continue
        if frm == "CNY" and to != "CNY":
            if rate == 0:
                continue
            rate = 1.0 / rate
            frm, to = to, frm
        elif to != "CNY":
            continue
        results.append({
            "from_currency": frm,
            "to_currency": to,
            "rate": round(rate, 8),
        })
    if not results:
        print("[提示] chinamoney 响应中没有可用汇率，跳过", file=sys.stderr)
        return None
    return {"date": record.get("date", ""), "rates": results}


# ── 推送到外部 API ──────────────────────────────────


def load_config():
    """读取 config.json；文件不存在时返回空配置。"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[错误] 读取配置文件失败: {e}", file=sys.stderr)
        return None
    if not isinstance(config, dict):
        print("[错误] config.json 顶层必须是 JSON 对象", file=sys.stderr)
        return None
    return config


def push_json(data, config):
    """将数据以 JSON POST 到配置的 API URL。"""
    api_cfg = config.get("push_api", {})
    if not isinstance(api_cfg, dict):
        print("[错误] push_api 必须是 JSON 对象", file=sys.stderr)
        return False
    url = api_cfg.get("url", "").strip()
    if not url:
        print("[错误] 配置文件中 push_api.url 未设置", file=sys.stderr)
        return False

    method = str(api_cfg.get("method", "POST")).upper()
    if method != "POST":
        print(f"[错误] 仅支持 POST 推送，当前配置为 {method}", file=sys.stderr)
        return False

    timeout = api_cfg.get("timeout", 15)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        print("[错误] push_api.timeout 必须是正数", file=sys.stderr)
        return False

    headers = dict(api_cfg.get("headers", {}) or {})
    headers.setdefault("Content-Type", "application/json")

    body = json.dumps(data, ensure_ascii=False).encode("utf-8")

    print(f"[推送] POST {url}")
    print(f"[推送] 数据大小: {len(body)} 字节")

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
        print(f"[推送成功] HTTP {resp.status}")
        if resp_body.strip():
            print(f"  响应: {resp_body[:200]}")
        return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:200]
        print(f"[推送失败] HTTP {e.code}: {e.reason}")
        if detail:
            print(f"  响应: {detail}")
        last_err = f"HTTP {e.code} {e.reason}"
    except Exception as e:
        print(f"[推送失败] {e}")
        last_err = str(e)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tag = date.today().strftime("%Y%m%d")
    log_file = LOG_DIR / f"push_error_{tag}.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(
            f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] 推送失败\n'
            f"  URL: {url}\n"
            f"  数据大小: {len(body)} 字节\n"
            f"  错误: {last_err}\n"
            f"{'-' * 60}\n"
        )
    print(f"[错误] 推送失败详情已写入日志: {log_file}", file=sys.stderr)
    return False

# ── 格式化输出 ──────────────────────────────────────


def table_for(rates, title=""):
    """为汇率列表生成格式化表格"""
    sep = "-" * 55
    header = f"{'源币':>5} → {'目标':>5}   {'汇率':>12}"
    lines = [sep, f"  {title}", sep, header, sep]
    for r in rates:
        rate_str = f"{float(r['rate']):>12,.4f}"
        lines.append(
            f"{r['from_currency']:>5} → {r['to_currency']:>5}   {rate_str}"
        )
    lines.append(sep)
    return "\n".join(lines)


def build_payload(smbs_rates, cm_data, query_date):
    """组装完整的推送 / JSON 输出数据"""
    payload = {
        "date": query_date.isoformat(),
        "smbs": smbs_rates,
    }
    if cm_data:
        payload["chinamoney"] = cm_data["rates"]
    return payload


def resolve_query_date(cli_date, config):
    """按命令行、配置文件、当天的优先级确定查询日期。"""
    value = cli_date or config.get("date")
    if not value:
        return date.today()
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as e:
        source = "--date" if cli_date else "config.json 中的 date"
        raise ValueError(
            f"{source} 格式错误，请使用 YYYY-MM-DD: {value}"
        ) from e


# ── 主入口 ──────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="汇率查询与推送")
    parser.add_argument("--date", "-d", type=str, default=None,
                        help="日期，格式 YYYY-MM-DD（优先于 config.json）")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true",
                        help="以 JSON 格式输出")
    output.add_argument("--push", action="store_true",
                        help="获取数据后推送到 config.json 配置的 API")
    args = parser.parse_args()

    config = load_config()
    if config is None:
        sys.exit(1)
    try:
        query_date = resolve_query_date(args.date, config)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    raw_smbs = fetch_smbs(query_date)
    if raw_smbs is None:
        print("[错误] smbs (韩元牌价) 获取失败，退出", file=sys.stderr)
        sys.exit(1)

    smbs = parse_smbs(raw_smbs)
    if not smbs:
        print("[错误] smbs 响应中没有可用汇率，取消输出和推送",
              file=sys.stderr)
        sys.exit(1)

    cm = fetch_chinamoney(query_date)
    if cm is None:
        print("[提示] chinamoney (人民币中间价) 获取失败，跳过", file=sys.stderr)

    payload = build_payload(smbs, cm, query_date)

    if args.push:
        if not config:
            print(f"[错误] 推送模式需要配置文件: {CONFIG_FILE}", file=sys.stderr)
            sys.exit(1)
        ok = push_json(payload, config)
        sys.exit(0 if ok else 1)

    elif args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    else:
        ds = query_date.strftime("%Y-%m-%d")
        print(f"\n  汇率  {ds}\n")
        print(table_for(smbs, "韩元牌价 (smbs.biz) — 1外币 = ?韩元"))
        print(f"  共 {len(smbs)} 种货币\n")

        if cm:
            print(table_for(cm["rates"], "人民币中间价 (chinamoney)"))
            print(f"  共 {len(cm['rates'])} 个货币对，交易日 {cm['date']}")
        else:
            print("  (chinamoney 数据不可用)")
        print(f"  数据来源: smbs.biz / chinamoney.com.cn")


if __name__ == "__main__":
    main()
