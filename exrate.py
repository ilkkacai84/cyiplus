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
import os
import re
import sys
import time

# ── 配置 ────────────────────────────────────────────
SMBS_URL = "http://www.smbs.biz/Flash/TodayExRate_flash.jsp?tr_date={date}"
CHINAMONEY_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"

CURRENCY_MAP = {"CNH": "CNY"}

MAX_RETRIES = 5
RETRY_DELAY = 60
LOG_DIR = "logs"
CONFIG_FILE = "config.json"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


# ── 通用工具 ────────────────────────────────────────


def log_failure(url, attempts, last_err, source_name=""):
    """将失败信息写入日志文件"""
    os.makedirs(LOG_DIR, exist_ok=True)
    tag = date.today().strftime("%Y%m%d")
    log_file = os.path.join(LOG_DIR, f"exrate_error_{tag}.log")
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

            if not check_ok(obj):
                last_err = "返回内容异常，未通过有效性检查"
                print(f"[{source_name}][第{attempt}次] {last_err}，{RETRY_DELAY}秒后重试...",
                      file=sys.stderr)
            else:
                return obj

        except Exception as e:
            last_err = str(e)
            print(f"[{source_name}][第{attempt}次] 请求失败: {last_err}，{RETRY_DELAY}秒后重试...",
                  file=sys.stderr)

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

    currencies, seen = [], set()
    for key, vals in params.items():
        if re.match(r"^[A-Z]{3}$", key) and key not in seen:
            seen.add(key)
            currencies.append((key, vals[0]))

    updown_map, diff_map = {}, {}
    for key, vals in params.items():
        m = re.match(r"^updown(\d+)$", key)
        if m:
            updown_map[int(m.group(1))] = int(vals[0])
        m = re.match(r"^diff(\d+)$", key)
        if m:
            diff_map[int(m.group(1))] = vals[0]

    results = []
    for i, (code, rate_str) in enumerate(currencies, start=1):
        rate = float(rate_str.replace(",", ""))
        display = CURRENCY_MAP.get(code, code)
        results.append({
            "from_currency": display,
            "to_currency": "KRW",
            "rate": f"{rate:.8f}".rstrip('0').rstrip('.'),
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
        check_ok=lambda d: isinstance(d, dict) and "records" in d
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
        match = [r for r in records if r["date"] == ds]
        if not match:
            print(f"[提示] chinamoney 无 {ds} 的数据（可能非交易日），跳过", file=sys.stderr)
            return None
        record = match[0]
    else:
        record = records[0]

    head = data["data"]["head"]
    values = record["values"]

    results = []
    for pair, val_str in zip(head, values):
        frm, to, mult = parse_chinamoney_pair(pair)
        if frm is None:
            continue
        rate = float(val_str) / mult
        # 统一格式：始终让 from_currency 为外币, to_currency 为 CNY
        if to != "CNY":
            # 例如 CNY/MOP → 翻转成 MOP/CNY, rate 取倒数
            rate = 1.0 / rate
            frm, to = to, frm
        results.append({
            "from_currency": frm,
            "to_currency": to,
            "rate": f"{rate:.8f}".rstrip('0').rstrip('.'),
        })
    return {"date": record["date"], "rates": results}


# ── 推送到外部 API ──────────────────────────────────


def load_config():
    """读取 config.json，失败返回 None"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[错误] 配置文件 {CONFIG_FILE} 不存在", file=sys.stderr)
        return None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[错误] 读取配置文件失败: {e}", file=sys.stderr)
        return None


def push_via_uri(data, config):
    """
    将 data (dict) 以 JSON 格式 POST 到配置的 API URL。
    请求体为 JSON，Content-Type: application/json。
    """
    api_cfg = config.get("push_api", {})
    url = api_cfg.get("url", "").strip()
    if not url:
        print("[错误] 配置文件中 push_api.url 未设置", file=sys.stderr)
        return False

    timeout = api_cfg.get("timeout", 15)
    headers = api_cfg.get("headers", {}) or {}
    headers.setdefault("Content-Type", "application/json")

    # JSON 编码为 bytes
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")

    print(f"[推送] POST {url}")
    print(f"[推送] 数据大小: {len(body)} 字节")

    # POST 请求
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
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

    # 写失败日志
    os.makedirs(LOG_DIR, exist_ok=True)
    tag = date.today().strftime("%Y%m%d")
    log_file = os.path.join(LOG_DIR, f"push_error_{tag}.log")
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


def table_for(rates, title="", show_change=True):
    """为汇率列表生成格式化表格"""
    labels = {0: "→ 持平", 1: "↓ 下跌", 3: "↑ 上涨"}
    sep = "-" * 55
    lines = [sep, f"  {title}", sep]
    if show_change:
        header = f"{'源币':>5} → {'目标':>5}   {'汇率':>12}   {'涨跌':>9}  {'状态'}"
    else:
        header = f"{'源币':>5} → {'目标':>5}   {'汇率':>12}"
    lines.append(header)
    lines.append(sep)
    for r in rates:
        chg = r.get("change")
        d = r.get("direction")
        rate_str = f"{float(r['rate']):>12,.4f}"
        if show_change and chg is not None and d is not None:
            status = labels.get(d, "?")
            lines.append(
                f"{r['from_currency']:>5} → {r['to_currency']:>5}   "
                f"{rate_str}   {chg:>+9.2f}  {status}"
            )
        else:
            lines.append(
                f"{r['from_currency']:>5} → {r['to_currency']:>5}   "
                f"{rate_str}"
            )
    lines.append(sep)
    return "\n".join(lines)
def build_payload(smbs_rates, cm_data, query_date):
    """组装完整的推送 / JSON 输出数据"""
    payload = {
        "smbs": smbs_rates,
    }
    if cm_data:
        payload["chinamoney"] = cm_data["rates"]
    return payload


# ── 主入口 ──────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="汇率查询与推送")
    parser.add_argument("--date", "-d", type=str, default=None,
                        help="日期，格式 YYYY-MM-DD（优先于 config.json）")
    parser.add_argument("--json", action="store_true",
                        help="以 JSON 格式输出")
    parser.add_argument("--push", action="store_true",
                        help="获取数据后推送到 config.json 配置的 API")
    args = parser.parse_args()

    # 解析日期：CLI --date > 配置文件 date > 今天
    query_date = date.today()
    cfg_date = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                cfg_date = cfg.get("date", "") or None
        except Exception:
            pass  # 配置文件读取失败不阻塞

    if args.date:
        try:
            query_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"[错误] 日期格式错误，请使用 YYYY-MM-DD: {args.date}",
                  file=sys.stderr)
            sys.exit(1)
    elif cfg_date:
        try:
            query_date = datetime.strptime(str(cfg_date), "%Y-%m-%d").date()
        except ValueError:
            print(f"[错误] config.json 中 date 格式错误: {cfg_date}，使用今天",
                  file=sys.stderr)

    # 获取数据（两个 API 必须都成功）
    raw_smbs = fetch_smbs(query_date)
    cm = fetch_chinamoney(query_date)

    if raw_smbs is None:
        print("[错误] smbs (韩元牌价) 获取失败，退出", file=sys.stderr)
        sys.exit(1)
    if cm is None:
        print("[提示] chinamoney (人民币中间价) 获取失败，跳过", file=sys.stderr)

    smbs = parse_smbs(raw_smbs)
    payload = build_payload(smbs, cm, query_date)

    if args.push:
        # 推送模式
        cfg = load_config()
        if cfg is None:
            sys.exit(1)
        ok = push_via_uri(payload, cfg)
        sys.exit(0 if ok else 1)

    elif args.json:
        # JSON 输出
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    else:
        # 表格输出
        ds = query_date.strftime("%Y-%m-%d")
        print(f"\n  汇率  {ds}\n")
        print(table_for(smbs, "韩元牌价 (smbs.biz) — 1外币 = ?韩元", show_change=False))
        print(f"  共 {len(smbs)} 种货币\n")

        if cm:
            print(table_for(cm["rates"], "人民币中间价 (chinamoney)", show_change=False))
            print(f"  共 {len(cm['rates'])} 个货币对，交易日 {cm['date']}")
        else:
            print("  (chinamoney 数据不可用)")
        print(f"  数据来源: smbs.biz / chinamoney.com.cn")
        print(f"\n  --- smbs 原始报文 (截取) ---")
        print(f"  {raw_smbs[:150].strip()}")
        print(f"  ...")
        print(f"  {raw_smbs[-150:].strip()}")


if __name__ == "__main__":
    main()
