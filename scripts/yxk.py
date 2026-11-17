#!/usr/bin/env python3
"""游侠客只读数据抓取（自包含，仅标准库，无需 API Key / 登录）。

用法：
    python3 yxk.py cities
    python3 yxk.py search 疾速 --city 上海 --from 2026-10-01 --to 2026-10-08 --json
    python3 yxk.py leaders 48168                 # 单线路列团期 + 领队
    python3 yxk.py leaders 48168 36930 --json    # 多线路
    python3 yxk.py html 疾速 --city 上海 --from 2026-10-01 --to 2026-10-08 -o out.html

关键点：
  * 搜索走 POST /app/api/app/search/web/product（分页 20 条/页）
  * 团期+领队必须走 v3：/api/m/v3/product/lines/batches?pid=&oid=
    （v2 的同名接口没有 servicePersonList，拿不到领队）
  * 领队随排班推进出现：status==3「确定成行」常见已派，但 status==1
    「可报名」也可能已派 —— **不可用 status 过滤后再找领队**（详见 SKILL.md 第 3 节）
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

BASE = "https://m.youxiake.com"
UA = "youxiake-routes-skill/1.1.1 (+https://m.youxiake.com/)"

# 站点命名前缀（集合点），归并时需剥离
PREFIX_RE = re.compile(
    r"^(浦东龙阳|宝山出发|宝山|松江|嘉定|金山|青浦|闵行|奉贤|崇明|"
    r"世纪大道|莘庄|七宝|浦东新区|黄浦区|徐汇|静安|普陀|虹口|杨浦|长宁)[·]?"
)
# 系列前缀（营销系列名），归并时需再剥离一层
SERIES_RE = re.compile(
    r"^(疾速追山|疾速入门|疾速浪漫|疾速挑战|疾速|轻装|进阶|休闲|深度)[·]?"
)


# ---------------------------------------------------------------- HTTP

def _request(path: str, *, form: dict | None = None, timeout: float = 20,
             retries: int = 2) -> dict:
    url = path if path.startswith("http") else BASE + path
    headers = {"Accept": "application/json", "User-Agent": UA}
    data = None
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form).encode()
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers,
                                         method="POST" if form is not None else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"请求失败：{url} ({last})")


def _ok(result: dict, ctx: str) -> dict:
    if result.get("code") != 200:
        raise RuntimeError(f"{ctx}失败：{result.get('msg') or result.get('code')}")
    return result


# ---------------------------------------------------------------- 城市

def city_catalog() -> list[dict]:
    """城市站点全集。

    接口返回三段：sites(主站 14 个，含上海 sitecode=2) / secondsites(次级站) /
    citys(目的地城市 39 个)。搜索用的 sitecode 三段都可能有，需合并。
    """
    d = _ok(_request("/api/m/index/city?lat=0&lng=0"), "读取城市站点")
    data = d.get("data") or {}
    out, seen = [], set()
    for key in ("sites", "secondsites", "citys"):
        for c in data.get(key) or []:
            if c.get("name") and c["name"] not in seen:
                seen.add(c["name"])
                out.append(c)
    return out


def resolve_city(name: str) -> dict:
    cat = city_catalog()
    for c in cat:
        if c.get("name") == name:
            return c
    raise RuntimeError(
        f"未找到城市「{name}」；可用：{', '.join(c['name'] for c in cat[:30])}…")


# ---------------------------------------------------------------- 搜索

def search(keyword: str, city: str = "上海", *, pages: int = 10,
           start: str = "", end: str = "", days: str = "", month: str = "",
           order: str = "0") -> tuple[list[dict], int, int]:
    """返回 (products, total_page, record_count)。"""
    site = resolve_city(city)
    out: list[dict] = []
    total_page = 0
    record = 0
    for page in range(1, max(1, pages) + 1):
        form = {"keyword": keyword.strip(), "lat": 0, "lng": 0,
                "sitecode": site["sitecode"], "theme": 0, "id": 0, "page": page,
                "day": days, "month": month, "startTime": start,
                "endTime": end, "order": order}
        d = _ok(_request("/app/api/app/search/web/product", form=form), "搜索线路")
        dd = d.get("data") or {}
        items = list(dd.get("list") or [])
        total_page = int(dd.get("totalPage") or 0)
        record = int(dd.get("recordCount") or record)
        out.extend(items)
        if not items or page >= total_page:
            break
    # 按 pid 去重
    seen, uniq = set(), []
    for it in out:
        if it.get("pid") and it["pid"] not in seen:
            seen.add(it["pid"])
            uniq.append(it)
    return uniq, total_page, record


# ---------------------------------------------------------------- 产品底册（抗搜索不稳定）
def _registry_path(city: str, keyword: str) -> pathlib.Path:
    """底册文件路径：累积历史上出现过的 pid 及其元数据，跨运行持久化。"""
    key = f"{city}_{keyword}".replace("/", "-")
    d = pathlib.Path.home() / ".cache" / "youxiake-skill"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"registry_{key}.json"


def _product_name_via_detail(pid: int) -> str:
    """搜索漏返回时，用详情接口兜底拿线路名（搜索接口对相同参数返回不稳定）。"""
    try:
        d = _ok(_request(f"/api/m/product/app/detail?pid={pid}&oid="), f"线路 {pid} 详情")
        prod = (d.get("data") or {}).get("product") or {}
        return prod.get("product_name") or str(pid)
    except Exception:  # noqa: BLE001
        return str(pid)


def gather_products(keyword: str, city: str, *, pages: int = 10,
                   start: str = "", end: str = "", month: str = "",
                   days: str = "", order: str = "0") -> list[dict]:
    """稳健取产品列表：search 结果 ∪ 底册里「上次有、本次搜索漏返回」的 pid。

    根因：搜索接口对相同参数返回的产品集合不稳定（同 keyword+日期范围，
    本次调用可能漏掉部分产品，连不带日期的全站搜索也会漏），导致 html 清单
    漏线路、diff 误报「下架」。底册把历史上出现过的 pid 及其元数据持久化，
    每次并集补回漏网产品，再由 enrich_leaders 逐 pid 拉 batches_v3 取得
    当前真实团期（无在售班期的 pid 会被 filter_batches 自然丢弃，不会幽灵复现）。
    """
    products, tp, rc = search(keyword, city, pages=pages, start=start,
                              end=end, month=month, days=days, order=order)
    rp = _registry_path(city, keyword)
    reg: dict = {}
    if rp.exists():
        try:
            reg = json.loads(rp.read_text())
        except Exception:  # noqa: BLE001
            reg = {}
    seen = {str(p["pid"]) for p in products}
    restored = 0
    for pid_str, meta in reg.items():
        if pid_str in seen:
            continue
        name = meta.get("productName") or _product_name_via_detail(int(pid_str))
        products.append({
            "pid": int(pid_str),
            "productName": name,
            "adultprice": meta.get("adultprice"),
            "daysLabel": meta.get("daysLabel", ""),
            "typeLable": meta.get("typeLable", ""),
            "peopleLabel": meta.get("peopleLabel", ""),
            "star": None,
            "levelTip": "",
        })
        restored += 1
    # 把本次（含恢复）的全部产品写回底册，累积历史 pid，永不丢弃
    for p in products:
        reg[str(p["pid"])] = {
            "productName": p.get("productName"),
            "adultprice": p.get("adultprice"),
            "daysLabel": p.get("daysLabel", ""),
            "typeLable": p.get("typeLable", ""),
            "peopleLabel": p.get("peopleLabel", ""),
        }
    rp.write_text(json.dumps(reg, ensure_ascii=False))
    if restored:
        print(f"（底册补回 {restored} 个搜索漏返回的产品）", file=sys.stderr)
    return products


# ---------------------------------------------------------------- 团期 + 领队（v3）

def batches_v3(pid: int, oid: str = "") -> list[dict]:
    """读取线路的团期（含领队）。必须用 v3，v2 无 servicePersonList。"""
    d = _ok(_request(f"/api/m/v3/product/lines/batches?pid={pid}&oid={oid}"),
            f"读取线路 {pid} 团期")
    out: list[dict] = []
    for pkg in (d.get("data") or {}).get("dailyPackageList") or []:
        for b in pkg.get("batchList") or []:
            b["_pkgName"] = pkg.get("dailyPkgName")
            out.append(b)
    return out


def outdoor_level(pid: int, oid: str = "") -> dict:
    """读取线路的户外难度星级。

    必须用 `/api/m/product/app/detail`（app 版），普通
    `/api/m/product/lines/detail` 不返回 productOutdoorLevel。
    返回 {star, levelTip, starTitle}；无该字段时 star 为 None。
    """
    try:
        d = _ok(_request(f"/api/m/product/app/detail?pid={pid}&oid={oid}"), f"读取线路 {pid} 难度")
    except Exception:  # noqa: BLE001
        return {"star": None, "levelTip": "", "starTitle": ""}
    lvl = (d.get("data") or {}).get("productOutdoorLevel") or {}
    raw = lvl.get("solidStarV2")
    try:
        star = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        star = None
    return {"star": star, "levelTip": lvl.get("levelTip") or "",
            "starTitle": lvl.get("starTitle") or ""}


def enrich_levels(products: list[dict], *, workers: int = 8) -> None:
    """并发给每条线路挂上 star / levelTip（原地修改）。"""
    def load(p: dict) -> tuple[int, dict]:
        return p["pid"], outdoor_level(p["pid"])

    got: dict[int, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for pid, lv in pool.map(load, products):
            got[pid] = lv
    for p in products:
        lv = got.get(p["pid"]) or {}
        p["star"] = lv.get("star")
        p["levelTip"] = lv.get("levelTip", "")


# ---------------------------------------------------------------- 用户评价

# 评论接口：`/api/m/product/lines/evaluation?pid=&page=&sortName=&tagName=`
# （由移动端 chunk `app.js` 的 `getReviewList` 定位；无需登录）
# 返回 data.{num, totalpage, pagesize, tags[], list[]}
# 单条字段：username/avatar/addtime(10位秒)/content(含</br>)/stars[]/imgs[]/
#   totalityStar(1-5 总评)/emotionContent("棒极啦")/quality(1=平台精选置顶)/
#   startTime("今年 10-11")/pkgname/likeNum/reply/pjId/oid
EVALUATION_API = "/api/m/product/lines/evaluation"


def evaluations(pid: int, page: int = 1, *, sort_name: str = "",
                tag_name: str = "") -> dict:
    """读取某线路的用户评价（一页 21 条）。

    返回 {num, totalpage, pagesize, tags, list}。

    ⚠️ **`sort_name` 决定排序语义，务必显式传 `"time"`**：
      * `""`（默认）—— 不是纯时间序！平台把 4 条「精选」置顶（可能是去年的），
        再把其余按**某种综合排序**混排。实测 pid 57512 第 1 页只有 5 条 10-17 的评价，
        另外 6 条 10-17 的评价被排到了**第 19 页**（中间隔着 2025-09 的老评价）。
        依赖默认序取「最近 N 条」会**静默漏掉最新评价**。
      * `"time"` / `"new"` / `"addtime"` / `"desc"` —— 实测均为**纯 addtime 倒序**，
        无精选置顶，可安全用于「最近 N 条」和「某批次全量」。
    """
    q = urllib.parse.urlencode({
        "pid": pid, "page": page,
        "sortName": sort_name, "tagName": tag_name,
    })
    d = _ok(_request(f"{EVALUATION_API}?{q}"), f"读取线路 {pid} 评价")
    data = d.get("data") or {}
    return {
        "num": data.get("num") or 0,
        "totalpage": data.get("totalpage") or 0,
        "pagesize": data.get("pagesize") or len(data.get("list") or []),
        "tags": data.get("tags") or [],
        "list": data.get("list") or [],
    }


def recent_evaluations(pid: int, limit: int = 10, *, skip_featured: bool = True,
                       max_pages: int | None = None) -> list[dict]:
    """取按时间倒序的最近 N 条评价（自动跨页）。

    ⚠️ 必须用 `sort_name="time"` 请求。默认排序不是时间序（精选置顶 + 综合混排），
    会把最新评价甩到很后面的页，导致「最近 N 条」静默漏数据 —— 2026-10-19 实测
    pid 57512：默认序第 1 页只有 5 条 10-17 评价，另 6 条落在第 19 页。

    ⚠️ 每页 21 条，翻页上限按 `limit` 反推（而非固定 5 页）—— 固定上限会让
    `--limit 200` 静默只回 100 余条（2026-10-14 踩到：请求 200 实收 104）。
    """
    if max_pages is None:
        max_pages = max(3, int(limit / 21 * 1.5) + 2)
    out: list[dict] = []
    seen: set = set()
    page = 1
    while len(out) < limit and page <= max_pages:
        r = evaluations(pid, page, sort_name="time")
        items = r["list"]
        if not items:
            break
        for x in items:
            if skip_featured and x.get("quality") == 1:
                continue  # 精选置顶（time 序下通常已不存在，保留兜底）
            key = x.get("pjId") or x.get("oid") or id(x)
            if key in seen:
                continue
            seen.add(key)
            out.append(x)
        if page >= r["totalpage"]:
            break
        page += 1
    out.sort(key=lambda x: x.get("addtime") or 0, reverse=True)
    return out[:limit]


def evaluations_by_batch(pid: int, batch: str, *, max_pages: int | None = None,
                         sort_name: str = "time") -> list[dict]:
    """取某线路**某个团期**的全部评价。

    `batch` 支持 `2026-10-17` / `10-17` / `今年 10-17` 三种写法，内部统一归一化后
    与接口的 `startTime` 字段比对。

    ⚠️ `startTime` 是**相对日期字符串**：今年的是「今年 10-17」，跨年的会变成
    绝对日期「2025-12-27」。故匹配必须按归一化后的 (年, 月, 日) 比，不能直接
    字符串相等 —— 否则跨年查历史批次会全空。

    时间倒序扫描遇到「早于目标批次」即可停（评价按行程日聚集提交），避免翻 40 页。
    """
    target = _norm_batch(batch)
    if target is None:
        raise ValueError(f"无法解析批次日期：{batch!r}（示例：2026-10-17）")
    if max_pages is None:
        max_pages = 40
    out: list[dict] = []
    seen: set = set()
    for page in range(1, max_pages + 1):
        r = evaluations(pid, page, sort_name=sort_name)
        items = r["list"]
        if not items:
            break
        earliest = None
        for x in items:
            key = x.get("pjId") or x.get("oid")
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            st = _norm_batch(x.get("startTime") or "")
            if st == target:
                out.append(x)
            if st is not None:
                earliest = st if earliest is None else min(earliest, st)
        # 目标批次已过去（本页最旧的行程日都早于目标）→ 后面不可能再有
        if earliest is not None and earliest < target:
            break
        if page >= r["totalpage"]:
            break
    out.sort(key=lambda x: x.get("addtime") or 0, reverse=True)
    return out


def _norm_batch(s: str) -> tuple[int, int, int] | None:
    """把「今年 10-17」/「10-17」/「2025-12-27」归一化为 (年, 月, 日)。"""
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.match(r"^(?:今年\s*)?(\d{1,2})-(\d{1,2})$", s)
    if m:
        return dt.date.today().year, int(m.group(1)), int(m.group(2))
    return None


def enrich_leaders(products: list[dict], *, workers: int = 6) -> None:
    """并发给每条线路挂上 batches 与 leaders 汇总（原地修改）。"""
    def load(p: dict) -> tuple[int, list[dict]]:
        try:
            return p["pid"], batches_v3(p["pid"])
        except Exception:  # noqa: BLE001
            return p["pid"], []

    result: dict[int, list[dict]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for pid, bs in pool.map(load, products):
            result[pid] = bs

    for p in products:
        bs = result.get(p["pid"], [])
        org = origin_of(p.get("productName", ""))
        p["origin"] = org
        p["batches"] = [{
            "batchId": b.get("batchId"),
            "date": (b.get("dateRange") or "").split("~")[0],
            "dateRange": b.get("dateRange"),
            "price": b.get("adultPrice") or b.get("price"),
            "status": b.get("status"),
            "statusLabel": b.get("statusLabel") or {1: "可报名", 3: "确定成行", 2: "名额暂满"}.get(b.get("status"), ""),
            "memberCount": b.get("memberCount"),
            "limitMax": b.get("limitMax"),  # 容量上限；缺失会导致余位/超售无法判断
            "festival": b.get("festival") or "",
            "batchLimit": b.get("batchLimitDesc") or "",
            "origin": org,  # 集合点（主站/浦东龙阳/宝山出发…），用于区分同日同名团期
            "leads": [{"name": s.get("name"), "identity": s.get("identity"),
                       "uid": s.get("uid"), "avatar": s.get("avatar")}
                      for s in (b.get("servicePersonList") or [])],
        } for b in bs]
        p["leaders"] = sorted({l["name"] for b in p["batches"] for l in b["leads"]})
        p["leadBatchCount"] = sum(1 for b in p["batches"] if b["leads"])
        p["openBatchCount"] = sum(1 for b in p["batches"] if b["status"] in (1, 3))


def filter_city(products: list[dict], city: str) -> list[dict]:
    """按出发地过滤。

    ⚠️ sitecode 只影响排序，不排除外地线路 —— 实测「上海站」搜疾速会混入
    广州/杭州/苏州/郑州等出发的线路（55 条里仅 27 条真正上海出发）。
    必须本地按 placeLabel 二次过滤，末尾的「出发」二字两种写法都要兼容
    （「上海市出发」/「上海出发」）。
    """
    key = city.replace("市", "")
    return [p for p in products
            if key in (p.get("placeLabel") or "").replace("市", "")]


def filter_batches(products: list[dict], start: str = "", end: str = "") -> list[dict]:
    """按出发日过滤团期。

    注意：搜索接口的 startTime/endTime 并不严格生效（实测返回站点全部相关产品），
    所以日期过滤必须在本地对 batches 再做一次，并丢弃过滤后无团期的线路。
    """
    if not start and not end:
        return products
    out = []
    for p in products:
        bs = [b for b in p.get("batches") or []
              if (not start or (b.get("date") or "") >= start)
              and (not end or (b.get("date") or "") <= end)]
        if bs:
            p["batches"] = bs
            p["leaders"] = sorted({l["name"] for b in bs for l in b["leads"]})
            p["leadBatchCount"] = sum(1 for b in bs if b["leads"])
            p["openBatchCount"] = sum(1 for b in bs if b["status"] in (1, 3))
            out.append(p)
    return out


# ---------------------------------------------------------------- 归并

def core_name(name: str) -> str:
    s = PREFIX_RE.sub("", (name or "").strip())
    s = SERIES_RE.sub("", s)
    return s.split("|")[0].split("｜")[0].strip().replace(" ", "")


def origin_of(name: str) -> str:
    """提取集合点前缀，无前缀则返回「主站」。

    归并会把集合点从线路名里剥掉，导致同一天不同集合点的独立团期
    在清单里显示成同名行、无法区分（2026-10-12 用户反馈）。
    故把集合点单独留成团期级字段 origin，供展示与去重使用。
    """
    m = PREFIX_RE.match((name or "").strip())
    return m.group(1) if m else "主站"


def merge(products: list[dict]) -> list[dict]:
    """按 core_name 归并多集合点/多系列条目为一张卡。

    团期去重键用 batchId（唯一）；同一景区不同集合点是不同 batchId 的独立团期，
    因此归并后同一天可能出现「2 个集合点各发一期」，这是真实情况而非重复 ——
    用 segCount 记录当天可选的集合点数，报给用户时说明。
    """
    groups: dict[str, list[dict]] = {}
    for p in products:
        groups.setdefault(core_name(p.get("productName", "")), []).append(p)
    cards = []
    for core, ps in groups.items():
        # pid 升序作为次级键：否则价格并列的多集合点同 core 线路
        # 会因 API 返回顺序变化而让 head 漂移，导致 _flat 的比对键整体变更、
        # diff 报出虚假的「下架+新增」（2026-10-09 踩到：两期高阳山同为 ¥185）。
        ps_sorted = sorted(ps, key=lambda x: (-(x.get("adultprice") or 0),
                                              x.get("pid") or 0))
        head = ps_sorted[0]
        batch_map: dict = {}
        for p in ps:
            for b in p.get("batches") or []:
                key = b.get("batchId") or (b["dateRange"], b.get("status"))
                if key not in batch_map:
                    b["srcPid"] = p["pid"]  # 团期自身来源，供比对键使用
                    batch_map[key] = b
        # 同日排序：先按集合点（主站在前），再按价格 —— 保证同日多集合点
        # 团期相邻且顺序稳定，用户能一眼看出这是「同线路不同集合点」
        batches = sorted(batch_map.values(),
                         key=lambda x: (x["date"] or "",
                                        "0" if x.get("origin") == "主站" else "1" + (x.get("origin") or ""),
                                        x.get("price") or 0))
        # 同日多集合点计数
        day_count: dict[str, int] = {}
        for b in batches:
            day_count[b["date"]] = day_count.get(b["date"], 0) + 1
        for b in batches:
            b["segCount"] = day_count.get(b["date"], 1)
        cards.append({
            "name": core,
            "pid": head["pid"],
            "url": f"{BASE}/lines.html?id={head['pid']}",
            "price": min((p.get("adultprice") or 0) for p in ps if p.get("adultprice")) or head.get("adultprice"),
            "days": head.get("daysLabel", ""),
            "type": head.get("typeLable", ""),
            "registered": head.get("peopleLabel", ""),
            "star": max((p.get("star") or 0) for p in ps) or None,
            "levelTip": next((p.get("levelTip") for p in ps if p.get("levelTip")), ""),
            "batches": batches,
            "leaders": sorted({l for p in ps for l in p.get("leaders", [])}),
            "leadBatchCount": sum(1 for b in batches if b["leads"]),
            "openBatchCount": sum(1 for b in batches if b["status"] in (1, 3)),
            # 该线路涉及的全部集合点（团期级 origin 的去重汇总）
            "origins": sorted({b.get("origin") for b in batches if b.get("origin")}),
            "alts": [{"pid": p["pid"], "name": p.get("productName"),
                      "origin": p.get("origin", ""),
                      "n": len(p.get("batches") or [])} for p in ps_sorted[1:]],
        })
    cards.sort(key=lambda c: (-c["leadBatchCount"], -c["openBatchCount"]))
    return cards


# ---------------------------------------------------------------- 命令

def cmd_cities(_: argparse.Namespace) -> None:
    for c in city_catalog():
        print(f"{c['name']}\t{c['sitecode']}\t{c['mddId']}")


def cmd_leaders(args: argparse.Namespace) -> None:
    all_out = {}
    for pid in args.pid:
        bs = batches_v3(pid)
        all_out[str(pid)] = bs
        if args.json:
            continue  # 纯 JSON 模式不混入人类可读文本，否则输出无法被 json.load 解析
        print(f"\n=== pid {pid} · {len(bs)} 个团期 ===")
        for b in bs:
            leads = ", ".join(s.get("name", "") for s in (b.get("servicePersonList") or []))
            st = b.get("statusLabel") or {1: "可报名", 3: "确定成行", 2: "名额暂满"}.get(b.get("status"), "")
            mem = b.get("memberCount")
            print(f"  {b.get('dateRange',''):26s} {st:6s}"
                  f"{'报名' + str(mem) + '人' if mem is not None else '':10s} "
                  f"领队: {leads or '未排班'}")
    if args.json:
        print(json.dumps(all_out, ensure_ascii=False, indent=2))


def cmd_reviews(args: argparse.Namespace) -> None:
    """查某线路的用户评价。可给 pid，也可用 --keyword 先搜索再取第一条。"""
    pids = list(args.pid or [])
    if not pids and args.keyword:
        found, _, _ = search(args.keyword, args.city, pages=args.pages)
        found = filter_city(found, args.city) if not args.all_cities else found
        if not found:
            print(f"未找到「{args.keyword}」相关线路", file=sys.stderr)
            return
        if len(found) > 1 and not args.first:
            print(f"「{args.keyword}」命中 {len(found)} 条，请指定 pid：", file=sys.stderr)
            for p in found:
                print(f"  {p['pid']}\t{p.get('productName')}", file=sys.stderr)
            return
        pids = [found[0]["pid"]]

    all_out = {}
    for pid in pids:
        meta = evaluations(pid, 1)
        batch_label = ""
        if args.batch:
            items = evaluations_by_batch(pid, args.batch)
            batch_label = f" · 批次 {args.batch}"
        elif args.all:
            items = meta["list"]
        else:
            items = recent_evaluations(pid, args.limit,
                                       skip_featured=not args.keep_featured)
        stars = [x.get("totalityStar") for x in items if x.get("totalityStar")]
        summary = {}
        if stars:
            summary = {
                "count": len(stars),
                "avg": round(sum(stars) / len(stars), 2),
                "dist": {str(s): stars.count(s) for s in sorted(set(stars))},
                "with_image": sum(1 for x in items if x.get("imageNum")),
                "images": sum(int(x.get("imageNum") or 0) for x in items),
                "replied": sum(1 for x in items if (x.get("reply") or "").strip()),
            }
        all_out[str(pid)] = {"meta": {k: meta[k] for k in
                                      ("num", "totalpage", "pagesize", "tags")},
                             "batch": args.batch or "",
                             "summary": summary,
                             "list": items}
        if args.json:
            continue
        print(f"\n=== pid {pid} · 共 {meta['num']} 条评价 / {meta['totalpage']} 页"
              f"{batch_label} ===")
        if meta.get("tags"):
            print("标签: " + "、".join(f"{t['tname']}({t['num']})"
                                       for t in meta["tags"][:8]))
        if not items:
            print("  （无评价）")
        elif summary:
            dist = " / ".join(f"{k}★×{v}" for k, v in sorted(
                summary["dist"].items(), key=lambda kv: -int(kv[0])))
            print(f"汇总: {summary['count']} 条 | 均分 {summary['avg']} | {dist} | "
                  f"带图 {summary['with_image']} 条（共 {summary['images']} 张） | "
                  f"官方已回复 {summary['replied']} 条")
        for i, x in enumerate(items, 1):
            ts = x.get("addtime")
            when = (dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                    if ts else "?")
            star = x.get("totalityStar")
            star_s = f"{star}★" if star else ""
            feat = "［精选］" if x.get("quality") == 1 else ""
            print(f"\n[{i}] {x.get('username')}  {when} {star_s}{feat}")
            detail = []
            if x.get("startTime"):
                detail.append(f"行程 {x['startTime']}")
            if x.get("pkgname"):
                detail.append(x["pkgname"])
            if x.get("imageNum"):
                detail.append(f"图x{x['imageNum']}")
            if x.get("likeNum") and str(x["likeNum"]) != "0":
                detail.append(f"赞{x['likeNum']}")
            if detail:
                print("    " + " | ".join(detail))
            print("    " + _plain(x.get("content") or "")[:400])
            if x.get("reply"):
                print(f"    ↳ 官方回复: {_plain(x['reply'])[:200]}")
    if args.json:
        print(json.dumps(all_out, ensure_ascii=False, indent=2))


def _plain(html_text: str) -> str:
    """把评价正文里的 </br> 等标签换成空白，压掉多余空行。"""
    t = re.sub(r"<br\s*/?>", " ", html_text or "")
    t = re.sub(r"</?[a-zA-Z]+[^>]*>", "", t)
    return " ".join(t.split())


def cmd_search(args: argparse.Namespace) -> None:
    products, tp, rc = search(args.keyword, args.city, pages=args.pages,
                              start=args.start, end=args.end, month=args.month,
                              order=args.order)
    if not args.all_cities:
        products = filter_city(products, args.city)
    print(f"# {args.city}站「{args.keyword}」：{len(products)} 条（站点命中 {rc} 条 / {tp} 页）",
          file=sys.stderr)
    if args.with_leaders:
        products = filter_city(products, args.city) if not args.all_cities else products
        enrich_leaders(products)
        products = filter_batches(products, args.start, args.end)
    if getattr(args, "min_star", 0):
        enrich_levels(products)
        products = [p for p in products
                    if p.get("star") is not None and p["star"] >= args.min_star]
        products.sort(key=lambda p: -p["star"])
    else:
        # 未指定 --min-star 时不请求星级（省 1 次/线路 的请求），
        # 输出里 star 列为「—」。要星级请加 --min-star（哪怕 0.1 也会拉取）。
        for p in products:
            p.setdefault("star", None)
            p.setdefault("levelTip", "")
    if args.json:
        print(json.dumps(products, ensure_ascii=False, indent=2))
        return
    for p in products:
        star = f"{p['star']:g}星" if p.get("star") is not None else "—"
        print(f"{p['pid']}\t{p.get('adultprice')}\t{star}\t{p.get('levelTip','')}\t"
              f"{p.get('daysLabel')}\t{p.get('placeLabel')}\t{p.get('productName')}")
        if p.get("leaders"):
            print(f"      领队: {', '.join(p['leaders'])}")


# ---------------------------------------------------------------- 快照与差异

def snapshot_path(city: str, keyword: str, start: str, end: str,
                  min_star: float = 0) -> pathlib.Path:
    """快照文件名必须包含全部筛选条件。

    否则不同筛选（如 --min-star 4 与全量）会写同一个文件、互相污染，
    导致 diff 报出大量虚假「下架」（2026-09-30 踩到）。
    """
    key = f"{city}_{keyword}_{start or 'all'}_{end or 'all'}"
    if min_star:
        key += f"_star{min_star:g}"
    key = key.replace("/", "-")
    d = pathlib.Path.home() / ".cache" / "youxiake-skill"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def _flat(cards: list[dict]) -> dict:
    """把线路卡摊平成 {线路名|团期来源 pid|batchId: 指标} 便于逐团期比对。

    键必须含 batchId —— 同一天可能有多个集合点的独立团期，
    用「名称|日期」做键会互相覆盖并漏报（2026-09-29 踩到）。

    键里的 pid 用团期自身的 srcPid（见 merge），不用线路卡的 head["pid"]：
    后者在价格并列时会漂移，导致同一团期前后键不一致、diff 误报
    「下架+新增」（2026-10-09 踩到）。
    """
    m = {}
    for c in cards:
        for b in c.get("batches") or []:
            src = b.get("srcPid") or c["pid"]
            m[f"{c['name']}|{src}|{b.get('batchId')}"] = {
                "date": b.get("date"), "line": c["name"],
                "status": b.get("statusLabel"),
                "member": b.get("memberCount"),
                "limit": b.get("limitMax"),  # 容量下调是重要变化形态，须参与比对
                "leads": ",".join(x["name"] for x in (b.get("leads") or [])),
            }
    return m


def cmd_html(args: argparse.Namespace) -> None:
    from html_builder import build  # 同目录，按需导入
    products = gather_products(args.keyword, args.city, pages=args.pages,
                              start=args.start, end=args.end, month=args.month)
    products = filter_city(products, args.city) if not args.all_cities else products
    enrich_leaders(products)
    products = filter_batches(products, args.start, args.end)
    enrich_levels(products)
    if getattr(args, "min_star", 0):
        products = [p for p in products
                    if p.get("star") is not None and p["star"] >= args.min_star]
    cards = merge(products)
    out = pathlib.Path(args.output)
    build(cards, out, city=args.city, keyword=args.keyword,
          start=args.start, end=args.end, record=len(products))
    n_lead = sum(c["leadBatchCount"] for c in cards)

    # 与上一快照比对，只报变化项（刷新场景下比全量更有用）
    snap = snapshot_path(args.city, args.keyword, args.start, args.end,
                         getattr(args, "min_star", 0))
    new = _flat(cards)
    if snap.exists():
        try:
            old = json.loads(snap.read_text())
            changes = compare(old, new)
            if changes:
                print(f"── 较上次的 {len(changes)} 处变化 ──")
                for line in changes:
                    print("  " + line)
            else:
                print("── 较上次无变化 ──")
        except Exception as exc:  # noqa: BLE001
            print(f"（快照比对跳过：{exc}）", file=sys.stderr)
    snap.write_text(json.dumps(new, ensure_ascii=False))

    print(f"已生成 {out}（{out.stat().st_size} B）｜线路 {len(cards)}"
          f"｜团期 {sum(len(c['batches']) for c in cards)}｜已派领队团期 {n_lead}")


def compare(old: dict, new: dict) -> list[str]:
    """返回人类可读的变化列表。"""
    out = []
    for k in sorted(set(old) | set(new), key=lambda x: (new.get(x) or old.get(x) or {}).get("date") or ""):
        p, c = old.get(k), new.get(k)
        name = (c or p)["line"]
        date = (c or p)["date"]
        if p is None:
            out.append(f"新增 {date} {name}｜报名{c['member']}/{c.get('limit')}｜领队{c['leads'] or '未排班'}")
            continue
        if c is None:
            out.append(f"下架 {date} {name}")
            continue
        ch = []
        if p["member"] != c["member"]:
            ch.append(f"报名 {p['member']}→{c['member']}")
        if p.get("limit") != c.get("limit"):
            ch.append(f"容量 {p.get('limit')}→{c.get('limit')}")
        if p["status"] != c["status"]:
            ch.append(f"状态 {p['status']}→{c['status']}")
        if p["leads"] != c["leads"]:
            ch.append(f"领队 {p['leads'] or '未排班'}→{c['leads'] or '未排班'}")
        if ch:
            out.append(f"{date} {name}｜" + "｜".join(ch))
    return out


def cmd_diff(args: argparse.Namespace) -> None:
    """不带参数时：刷新数据并与上次快照比对（等价于 html 的对比部分）。"""
    snap = snapshot_path(args.city, args.keyword, args.start, args.end,
                         getattr(args, "min_star", 0))
    products, _, _ = search(args.keyword, args.city, pages=args.pages,
                            start=args.start, end=args.end)
    products = filter_city(products, args.city) if not args.all_cities else products
    enrich_leaders(products)
    products = filter_batches(products, args.start, args.end)
    if getattr(args, "min_star", 0):
        enrich_levels(products)
        products = [p for p in products
                    if p.get("star") is not None and p["star"] >= args.min_star]
    new = _flat(merge(products))
    if not snap.exists():
        snap.write_text(json.dumps(new, ensure_ascii=False))
        print(f"首次快照已保存（{len(new)} 个团期）；下次运行即可看到变化。")
        return
    old = json.loads(snap.read_text())
    changes = compare(old, new)
    print(f"快照基线 {len(old)} 个团期 → 当前 {len(new)} 个团期")
    if changes:
        print(f"── {len(changes)} 处变化 ──")
        for line in changes:
            print("  " + line)
    else:
        print("无变化")
    snap.write_text(json.dumps(new, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="yxk", description="游侠客只读抓取")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("cities", help="列出城市站点").set_defaults(func=cmd_cities)

    s = sub.add_parser("search", help="搜索线路")
    s.add_argument("keyword")
    s.add_argument("--city", default="上海")
    s.add_argument("--from", dest="start", default="")
    s.add_argument("--to", dest="end", default="")
    s.add_argument("--month", default="")
    s.add_argument("--order", default="0", help="0 默认排序，3 销量优先")
    s.add_argument("--all-cities", action="store_true", help="保留其他出发城市的线路")
    s.add_argument("--pages", type=int, default=10)
    s.add_argument("--with-leaders", action="store_true", help="同时抓团期与领队（较慢）")
    s.add_argument("--min-star", type=float, default=0, help="只看难度 ≥N 星的线路（4=进阶挑战以上）")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)

    l = sub.add_parser("leaders", help="查团期与领队（v3）")
    l.add_argument("pid", type=int, nargs="+")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_leaders)

    r = sub.add_parser("reviews", help="查线路的用户评价（最近 N 条）")
    r.add_argument("pid", type=int, nargs="*", help="线路 pid；也可改用 --keyword")
    r.add_argument("--keyword", default="", help="按关键词先搜索再取第一条线路")
    r.add_argument("--city", default="上海")
    r.add_argument("--limit", type=int, default=10, help="取最近几条（默认 10）")
    r.add_argument("--batch", default="",
                   help="只看某个团期，如 2026-10-17（也接受 10-17）")
    r.add_argument("--all", action="store_true", help="取整页原始顺序（含精选置顶）")
    r.add_argument("--keep-featured", action="store_true",
                   help="保留平台精选置顶（默认剔除，因其非真实时间序）")
    r.add_argument("--first", action="store_true", help="--keyword 命中多条时直接取第一条")
    r.add_argument("--pages", type=int, default=10)
    r.add_argument("--all-cities", action="store_true")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_reviews)

    h = sub.add_parser("html", help="生成单文件 HTML 清单（自动与上次快照比对）")
    h.add_argument("keyword")
    h.add_argument("--city", default="上海")
    h.add_argument("--from", dest="start", default="")
    h.add_argument("--to", dest="end", default="")
    h.add_argument("--month", default="")
    h.add_argument("--pages", type=int, default=10)
    h.add_argument("--all-cities", action="store_true", help="保留其他出发城市的线路")
    h.add_argument("--min-star", type=float, default=0, help="只看难度 ≥N 星的线路")
    h.add_argument("-o", "--output", default="youxiake.html")
    h.set_defaults(func=cmd_html)

    d = sub.add_parser("diff", help="只刷新并列出与上次快照的差异（不生成 HTML）")
    d.add_argument("keyword")
    d.add_argument("--city", default="上海")
    d.add_argument("--from", dest="start", default="")
    d.add_argument("--to", dest="end", default="")
    d.add_argument("--pages", type=int, default=10)
    d.add_argument("--all-cities", action="store_true")
    d.add_argument("--min-star", type=float, default=0, help="与 html 一致，快照键含星级")
    d.set_defaults(func=cmd_diff)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
