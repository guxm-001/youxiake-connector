---
name: youxiake-routes
display_name: 游侠客线路查询
display_name_en: Youxiake Routes Finder
description: 查询游侠客（youxiake.com）某分站在售线路、团期、领队与用户评价，支持余位监测、变化对比，可生成单文件 HTML 清单。触发词：游侠客、游侠客线路、游侠客团期、游侠客领队、余位、youxiake。
description_zh: 查询游侠客各分站在售线路、团期、领队与报名情况，支持余位与超售监测、刷新变化对比、用户评价查询，并可生成可直接嵌入小程序的单文件 HTML 清单。
description_en: Query Youxiake branch routes, departures, leaders and user reviews. Supports seat availability, change tracking between refreshes, and generates a single-file HTML report.
category: Productivity
version: 1.1.1
author: 新敏
agent_created: true
---

# 游侠客线路 / 团期 / 领队查询

## 0. 执行入口（按优先级）

**首选：本技能自带脚本 `scripts/yxk.py`**（自包含，仅标准库，无 API Key）。

**先进入脚本目录**（技能可能被装在任意位置，不要写死绝对路径）：

```bash
cd <技能目录>/scripts      # 例如 ~/.workbuddy/skills/youxiake-routes/scripts
PY=python3                 # 需 Python 3.9+，系统自带 python3 即可
```

```bash
$PY yxk.py cities                                    # 城市 → sitecode

# ⚠️ keyword 必填、没有默认值。下面示例里的「疾速」只是举例，
#    换成任意主题/线路名即可：休闲 / 深度 / 亲子 / 徒步 / 露营 / 远征大环线…
$PY yxk.py search 疾速 --city 上海 --from 2026-10-01 --to 2026-10-08
$PY yxk.py search 疾速 --city 上海 --with-leaders --json   # 含团期+领队
$PY yxk.py search 疾速 --city 上海 --min-star 4      # 只看难度 ≥4 星
$PY yxk.py search 露营 --city 上海                    # 换个主题（不是只能查疾速）
$PY yxk.py search 远征大环线 --city 上海               # 或直接搜线路名

$PY yxk.py leaders 48168                             # 单线路全部团期 + 领队
$PY yxk.py reviews 39330 --limit 10                  # 最近 10 条用户评价（按 pid）
$PY yxk.py reviews --keyword 远征大环线 --limit 10    # 先搜线路名再取评价
$PY yxk.py reviews 39330 --all                       # 整页原始顺序（含平台精选置顶）
$PY yxk.py diff 疾速 --city 上海 --from 2026-10-01 --to 2026-10-08   # 只报变化
$PY yxk.py html 疾速 --city 上海 --from 2026-10-01 --to 2026-10-08 -o out.html
```

**唯一有默认值的是 `--city`（默认「上海」）** —— 其余参数要么必填，要么按需给。
用户问「查线路」时**不要自行假定主题**，先问清或按用户原话的关键词搜。

脚本用 Python 3.9+ 均可（已在 3.9.6 与 3.13.12 双版本验证），仅依赖标准库。

**`--pages` 要给足**：站点 5 页共 82 条，`--pages 1` 只能拿到 17 条。默认 `10` 页已覆盖全部。

**刷新场景用 `diff` 或 `html`**：两者都会自动与上次快照比对，只报变化项（报名数 / 状态 / 领队增减），比看全量更有效。快照存放在 `~/.cache/youxiake-skill/`。
⚠️ 比对键必须含 **`batchId`** —— 同一天可能有多个集合点的独立团期，用「线路名|日期」做键会互相覆盖并漏报（已内置处理）。
⚠️ 比对键里的 pid 必须取**团期自身的来源 pid**（`batch.srcPid`），**不能取线路卡的 `head["pid"]`** —— 价格并列（如同为 ¥185）或一方调价时 head 会漂移，导致键整体变更、diff 误报一批「下架 + 新增」（2026-10-09 踩到：两期高阳山 key 由 `48168` 翻转为 `57988`，一次报出 6 处虚假变化）。已内置处理。
⚠️ **`diff` 与 `html` 会给同一个快照文件（竞态）**：`diff` 先跑会消费掉变化，随后 `html` 显示「较上次无变化」。想同时拿「变化 + 清单」的做法：**只跑 `html`**（它内部自带比对并输出变化），或先 `html` 后 `diff`。
⚠️ **改了比对键 / 快照结构后必须删掉旧快照重建基线**：否则新旧键错位会把全部团期误判为「下架 + 新增」。删 `~/.cache/youxiake-skill/<城市>_<关键词>_<起>_<止>.json` 后重跑一次即可。

**次选：MCP `mcp__youxiake-readonly__*`** —— ⚠️ **但 MCP 走 v2 团期接口，拿不到领队**（详见第 3 节）。只在「只要线路名/价格/报名数、不关心领队」时用它，否则直接用脚本。

**兜底：PC 站 curl + 正则**（见第 5 节）—— 仅在脚本与 MCP 都不可用时使用。

## 1. 三个接口的分工（核心认知）

| 用途 | 接口 | 说明 |
|---|---|---|
| 搜索线路 | `POST /app/api/app/search/web/product` | 表单参数见下；20 条/页 |
| 城市站点 | `GET /api/m/index/city?lat=0&lng=0` | 返回 `sites`/`secondsites`/`citys` **三段**，需合并 |
| 团期 + 领队 | `GET /api/m/v3/product/lines/batches?pid=<PID>&oid=` | **必须 v3**，v2 无领队 |
| **难度星级** | `GET /api/m/product/app/detail?pid=<PID>&oid=` | ⚠️ **必须走 `app/detail`**，见第 9 节 |
| **用户评价** | `GET /api/m/product/lines/evaluation?pid=&page=&sortName=&tagName=` | 见第 10 节；21 条/页 |

搜索表单字段：`keyword / lat=0 / lng=0 / sitecode / theme=0 / id=0 / page / day / month / startTime / endTime / order`
（`order`：`0` 默认、`3` 销量优先；`day`：`10004` 表示 1~3 天）

## 2. ⚠️ 三个必踩的坑（已实测，脚本内已处理）

1. **`sitecode` 只影响排序，不排除外地线路。**
   实测「上海站」搜 `疾速` 返回 55 条，其中仅 27 条真正上海出发，其余是广州(7)/杭州(6)/苏州(6)/郑州(5)/新乡(3)/南京(1)。
   → **必须本地按 `placeLabel` 二次过滤**。注意两种写法：「上海市出发」和「上海出发」都要兼容（脚本用 `.replace("市","")` 后子串匹配）。脚本的 `filter_city()` 已处理。

2. **`startTime`/`endTime` 不严格生效。**
   传了 10-01~10-08，返回的仍是站点全部相关产品。
   → **日期过滤必须在本地对团期再做一次**（脚本 `filter_batches()`），并丢弃过滤后无团期的线路。

3. **`dailyPackageList` 里同一天可能有多个独立团期（不同集合点）。**
   这是真实情况，不是重复：高阳山 10-02 有 2 期（宜山路 / 浦东龙阳），虞山 10-03/05/06 各 2 期。
   → 团期去重键用 **`batchId`**（全局唯一，实测 60/60 无重复），**不要用 `(日期,状态)`**，否则会误合并。脚本在 `merge()` 里给每个团期打了 `segCount` 标记当天集合点数。

## 3. 领队查询（关键：必须 v3）

**接口**：`https://m.youxiake.com/api/m/v3/product/lines/batches?pid=<PID>&oid=`
- 路径：`data.dailyPackageList[].batchList[].servicePersonList[]`
- 字段：`uid / name / nickname / avatar / identity`（`identity` 一般为 `"领队"`）
- **无需登录**，`oid` 留空即可。

**规律：领队随排班推进出现，与团期状态不严格绑定。**
- 常见情况：`status == 3`（确定成行）的团期已派领队。但 **`status == 1`（可报名）也可能已派领队** —— 2026-09-29 实测：姑苏旺七 10-04 仍是「可报名」（10 人），却已配「新敏、踢踢」；同线路 10-02（8 人）则尚未排班。
- 所以**不要用 `status` 过滤后再找领队**，应遍历全部团期，凡 `servicePersonList` 非空即已排班。
- 领队按**团期**分配（同线路不同日期领队不同），人数不定：高阳山/虞山·雄鹰/远征大环线各 3 名，姑苏旺七 10-04 仅 2 名。
- **排班是滚动公布的**：上午查到「未公布」的团期，下午可能已派出领队（远征大环线 10-03 实测如此）。回答时按查询当刻的数据说，并说明这是实时值。

**v2 vs v3 差异对照**（这是本技能最容易搞错的地方）：

| | v2（CLI / MCP 用） | v3（必须用这个查领队） |
|---|---|---|
| 路径 | `/api/m/v2/product/lines/batches` | `/api/m/v3/product/lines/batches` |
| 层级 | 顶层 `data.batchList[]` | `data.dailyPackageList[].batchList[]` |
| 日期字段 | `dateFmt`（`2026-10-01`） | `dateRange`（`2026-10-01~2026-10-01`）/ `startDate`（`10/01`） |
| 领队 | ❌ 无 `servicePersonList` | ✅ 有 |
| 报名人数 | ❌ | ✅ `memberCount`、`avatarList` |
| 覆盖范围 | 仅近 3 个月（高阳山只到 10-31） | **v2 的超集**，更全（到 11-08） |
| 其他 | — | `festival`（"国庆"）、`batchLimitDesc`（"15人成行"）、`extraInfo.teamTypeLabel`（"独立团"）、`memberUrl`（名单页） |

**排除过的无效路径（别再试）**：CLI/MCP 源码、`youxiake_detail` 返回、PC 详情页 `/lines.html?id=N`（「领队」全是模板话术）、`/leader/` 频道（独立花名册，与线路无关）、`/api/leader/list`、`/api/lines/leader`、`/api/lines/team`、`/api/m/product/lines/schedule|leader|staff`。

**如何自行定位新接口**：`m.youxiake.com` 是 Vue SPA，接口藏在 JS 里。
`runtime.js` 提供 `chunk名:hash` 映射 → 拼 `https://m.youxiake.com/<build>/js/<chunk>.<hash>.js` 下载 → 检索字段名定位组件；或读 `youxiake_cli.py` 里写死的路径，**试相邻版本号**（v2→v3 就是这么找到的）。

## 4. 归并规则（避免重复卡）

线路名有三层修饰，归并需**依次剥离**：

```python
PREFIX = r'^(浦东龙阳|宝山出发|宝山|松江|嘉定|金山|青浦|闵行|奉贤|崇明|世纪大道|莘庄|七宝|浦东新区|黄浦区|徐汇|静安|普陀|虹口|杨浦|长宁)[·]?'  # 集合点
SERIES = r'^(疾速追山|疾速入门|疾速浪漫|疾速挑战|疾速|轻装|进阶|休闲|深度)[·]?'                                                # 系列名
core = re.sub(SERIES,'',re.sub(PREFIX,'',name)).split('|')[0].split('｜')[0].strip().replace(' ','')
```
> 以上与 `scripts/yxk.py` 的 `PREFIX_RE` / `SERIES_RE` **保持同步**（2026-10-14 校对：新增浦东新区/黄浦区及 6 个市区前缀）。

**已知系列前缀（2026-10-12 扩充）**：除上面的 `疾速*` 外，还存在
`侠野追风`（越野训练/月度赛，含 1.0/2.0/2.5 难度分档）、`无痕山野`（公益捡拾向）。
当前 `SERIES` 正则**未覆盖这两个**，故 `侠野追风1.0｜越野入门综合训练·高阳山` 会自成一张卡
（结果上不算错，因为它是独立产品线，但若想按「同一景区」跨系列汇总，需扩展 SERIES）。

### ⚠️ 归并会丢掉集合点，导致「同日同名」无法区分（2026-10-12 修复）
**症状**：按日期视图中，同一天出现多行完全同名的线路（如 10-17 三行「虞山」），
用户无法分辨哪行是哪个集合点 —— 因为归并时把 `浦东龙阳` / `宝山出发` 等前缀剥掉了。

**修复**：把集合点**提升为团期级字段 `origin`**：
- `origin_of(name)` 提取前缀，**无前缀 → `主站`**（不是空串，便于排序与展示）。
- `enrich_leaders()` 给每期打 `b["origin"]`，并在 card 上汇总 `origins` 列表。
- HTML 渲染 `originTag(b)`：蓝底标签，「主站」浅蓝、分站深蓝；「按日期」与「按线路」两视图都显示。
- 搜索 `match()` 支持集合点；页脚与占位符同步说明。
- `merge()` 的同日排序改为 **集合点优先（主站在前）→ 价格**，保证同日多集合点相邻且顺序稳定
  （此前只按价格排，同价时顺序不稳）。

**实测集合点取值**：`主站`（默认）/ `浦东龙阳` / `宝山出发`。
`虞山` 与 `姑苏旺七` 各有 **3 个**集合点；`高阳山`、`小恐龙` 各 2 个。

⚠️ **`alts`（「另有集合点」区块）已从卡片底部移除** —— 集合点现在直接标在每期上，该区块冗余。
`card["alts"]` 数据结构保留（含 `origin` 字段）备后用。

同一条景区线路会以 `疾速追山·虞山` / `浦东龙阳·疾速虞山` / `宝山出发·虞山` 三种命名出现，只剥集合点会留下 3 张重复卡。
实测：上海站国庆「疾速」26 条原始条目 → 归并后 **22 条真实线路**。

⚠️ **`虞山` 与 `虞山·雄鹰` 是两条不同线路，不该归并**（pid 36930 vs 49236，3.5★ vs 3★）。
分隔符目前只处理 `|` `｜`，**`·` 在核心名里被保留** —— 这恰好让 `虞山·雄鹰` 不被并入 `虞山`，是正确的。
若要动分隔符逻辑，务必保留这个区分。

## 4.1 发车节奏：周末为主，周二/三/四有少量团期

⚠️ **平台会删除已过期的团期。** 这是最容易导致误判的一点 —— 2026-10-09（周五）查 10-05~10-09 返回 0 期，
据此得出「工作日零团期」的结论；但 2026-10-12（周一）复查时，10-13/14/15 的工作日团期明确存在。
**过去的团期查不到 ≠ 当时没有发过车。** 判断发车规律必须看**未来**排期。

以未来 305 期（2026-10-13 ~ 2026-12-27）实测的星期分布：

| 星期 | 期数 | 说明 |
|---|---|---|
| 周一 | **0** | 不发车 |
| 周二 | 12 | 少量 |
| 周三 | 23 | 少量 |
| 周四 | 12 | 少量 |
| 周五 | **0** | 不发车 |
| 周六 | **149** | 主力 |
| 周日 | **109** | 主力 |

→ 周末占总量的 **84%**。周一与周五**从不发车**；周二/三/四合计 47 期（约 15%），
多为周末主线的补充档或状态为「可报名」的低量期。**查「本周团期」时必须覆盖全周，不能只取周末。**

⚠️ **`memberCount` 高的工作日团期值得留意**：如 10-13 周二高阳山 41/45（91%）且「确定成行」，
属于优先级很高的加排档（大概率承接了某个节假/调休或企业定制）。

## 5. 兜底：PC 站 curl（脚本/MCP 都不可用时）

PC 站首页与列表是**服务端渲染**，纯 curl + 正则即可，无需浏览器。
- 列表 URL：`https://www.youxiake.com/search/results/<placeId>-<region>-0-<day>-0-0.html`
  - 第 1 段 = 出发城市 placeId：上海 `86`、杭州 `16`、北京 `19`、广州 `15`、苏州 `23`、南京 `63`、无锡 `98`、成都 `288`。
  - 第 4 段 = 天数（`0` 全部、`1` 一天）。
- 站点 cookie：`curl -c /tmp/yxk.cookie "https://www.youxiake.com/?site=2"`（site=2 上海站）。后续只 `-b`，**不要同时 `-c`**（回写 cookie 会让筛选失效）。
- 分页：必须带 `?keyword=&spm=&page=N` 且带 `Referer` 指向同路径，缺一即退化为全国列表；仍有约 20% 页串入外地线路，需本地按 place 过滤。
- 单页 20 条，总量见页面 `共NN页/NNNN条`；抓完按 id 去重。

解析（按 `<div class="linesSearchList">` 切块）：

| 字段 | 正则 |
|---|---|
| id / 链接 | `href="(https://www\.youxiake\.com/lines\.html\?id=\d+[^"]*)"` → `id=(\d+)` |
| 类型+出发地 | `class="linesSearchPlace">([^<]*)<` |
| 标题 | `class="linesSearchTitle">.*?target="_blank">(.*?)</a>`（去掉「跟团游」尾巴） |
| 天数 | `行程天数：<i>([^<]*)</i>` |
| 报名人数 | `class="linesInfoNum"><i>([^<]*)</i>`（`3.35万` 需 ×10000） |
| 价格 | `￥<span>([^<]*)</span>`（空 = 暂无团期） |

## 6. 团期状态口径

`status`：`1` = 可报名（"可报名 大胆报名"）、`3` = 确定成行、`2` = 名额暂满。
「开放」= `1` 或 `3`。统计「开了几条」时**必须区分口径**：线路数 vs 团期数，两者常被混淆。

**余位字段（做「下单前哨」必用）**：`memberCount`（已报）/ `limitMax`（上限）。
`occupancy = memberCount / limitMax`，超过 **80%** 即为「余位紧张」，应主动提醒用户。
⚠️ **`limitMax` 是浮动的** —— 实测 10-01 高阳山在临近出发时由 45 **下调到 32**，占用率因此从 44% 跳到 84%。不能把容量当成常量缓存。
⚠️ **`memberCount` 可以 > `limitMax`** —— 实测 10-11 远征大环线 `53/45`（118%）并置 `status=2`「名额暂满」。容量是软约束，报名数可能含候补/超售。做占用率展示时要容忍 >100% 不崩。
⚠️ **`limitMax` 只存在于 v3 接口** —— v2 `/api/m/v2/product/lines/batches` **不返回**该字段。若用 v2 取团期，`limitMax` 必为 `None`，余位与超售均无法判断。**要算占用率就必须走 v3**。
⚠️ **`enrich_leaders()` 的字段白名单易漏字段** —— 它逐字段显式重建 batch dict，任何未列出的原始字段都会被丢弃。`limitMax` 曾因此被静默丢掉，导致 HTML 里 `limitMax` 全为 `None`、余位标签退化成「N人」（2026-10-09 踩到，已补）。**新增依赖字段时务必同步改这个白名单。**

**余位展示**：HTML 清单的 `seatHtml()` 渲染为 `已报/上限人 百分比%`，`>100%` 标红并加「超售」角标，`≥85%` 标黄提示「余位紧张」。

**临近出发的四种团期形态变化（刷新时优先关注）**：
1. **整期撤下** —— `batchId` 从接口消失（如 10-02 姑苏旺七辅期）。
2. **同日多期「收口」** —— 低量辅期撤下，报名并入主期（如 10-02 高阳山 16→24）。
3. **容量下调** —— `limitMax` 收缩，余位骤紧（如 10-01 高阳山 45→32）。
4. **领队换人** —— 名单人员替换（如 10-02 高阳山 兜菜→飞鹰）。**领队名单不是派出就固定**，刷新须逐期比对姓名而不只是有无。
5. **领队增补** —— 名单在已派基础上追加人手（如 10-11 远征大环线 3 人→4 人）；4★以上线路倾向配 3 人以上。

⚠️ **T-2 天（周五）是「撤期截止点」（2026-10-09 实测确认）**：报名仅个位数的单日团期会在出发前 2 天集中撤下。
当天 10-11 团期由 13 期收缩到 8 期，小恐龙(4人)/福马线(4人)/吴中十峰(5人)/光福小七尖(3人)/九龙之巅(7人)
五条线路当天团期全撤 —— 均未达「15人成行」门槛。**已核实为真**：这些线路在 10 月其他日期仍有团期，仅当天撤下。
→ 刷新时若见大批「下架」，先按此规律核对是否 T-2 正常收口，再判断是否为异常。

以上各类都说明：**平台在出发前持续收紧排班**，越接近出发日，数据波动越大，刷新频率应相应提高。

## 7. 交付形态

用户偏好本地单文件 HTML（可嵌入自己小程序 web-view）：浅色主题、卡片列表、支持按线路名/领队名/集合点搜索、"已派领队"筛选、集合点标签、"按日期 / 按线路"双视图。
数据以 `var DATA=[...]` 内联注入。

### 7.1 生成后必须校验（三道，缺一不可）

**改动 `html_builder.py` 模板后，务必跑一遍 —— 否则可能交付一个白屏页面。**

**第 1 道：数据完整性**
```bash
node -e "const h=require('fs').readFileSync('out.html','utf8');const d=JSON.parse(h.match(/var DATA=(\[.*?\]);/s)[1]);console.log('线路',d.length,'团期',d.reduce((a,c)=>a+c.batches.length,0))"
```

**第 2 道：JS 语法**（`build()` 内已内置 `_sanity_check`，会拦括号不平衡/占位符残留/数据未注入）
```bash
node --check <(sed -n '/<script>/,/<\/script>/p' out.html | sed '1d;$d')   # 或直接信任 _sanity_check
```

**第 3 道：真实浏览器渲染**（最可靠，务必在有模板改动时执行）

需要 `playwright-core` + 一个无头 Chromium。**本机没有可跳过**——前面两道已能拦住绝大多数问题。

```bash
node scripts/render_check.js <out.html>
# 期望输出：✅ 渲染自检通过（N 期，M 张卡片，JS 零错误）
```

`render_check.js` 会自动探测本机 playwright 与 Chromium；找不到时**打印提示并以退出码 0 跳过**，不阻塞主流程。

一次性准备（仅在需要第 3 道时）：
```bash
mkdir -p /tmp/yxk-deps && cd /tmp/yxk-deps
npm i playwright-core
npx playwright install chromium-headless-shell    # 约 100MB
NODE_PATH=/tmp/yxk-deps/node_modules node <技能>/scripts/render_check.js out.html
```

⚠️ **为什么要第 3 道（2026-10-12 事故）**：改模板时多写了一个 `}`，浏览器 JS 抛
`SyntaxError: Unexpected token '}'` → 页面只渲染到「筛选」就**一片空白**，
而 `yxk.py html` 照样打印「已生成 ... B」，**不看页面根本发现不了**。
`_sanity_check` 是事后补的 Python 侧防护；`render_check.js` 是端到端确认。

⚠️ **Chromium 版本会随 playwright 升级变化**：`render_check.js` 已做自动探测
（扫 `~/Library/Caches/ms-playwright/chromium_headless_shell-*/`），无需手改路径。
早期硬编码 `chromium_headless_shell-1234` 会因实际装的是 1243 而报
`Executable doesn't exist`。

## 8. ⛔ 边界：本技能只读，不支持代报名/代下单

**定性**：本技能及其全部脚本**只做数据读取**（线路/团期/领队/报名数）。用户若问「帮我报名 xx 团期」，答案是**不行**，且这不是工作量问题，是能力边界问题。

**为什么不能（2026-09-29 实测证据）**：

1. **下单链路整体需要登录态**。下单页 `https://m.youxiake.com/lines/batch/orders?pid=&starttime=&did=&batchPkgId=` 只是 SPA 壳（2.9 KB），真实逻辑在 `Order-Order` chunk 里。
2. **未登录访问用户态接口直接 401**：
   ```bash
   curl -s "https://m.youxiake.com/app/api/app/passenger/list"   # → {"code":401,"msg":"REFRESH TOKEN"}
   curl -s "https://m.youxiake.com/app/api/app/v2/user/myself"   # → uid:0（匿名）
   ```
   → 游客名单、联系人、优惠券、订单全部落在这道鉴权墙后面。
3. **登录方式**：`/login` + `/login/bindphone`（手机号+短信验证码），或微信授权。**短信验证码只发到用户本人手机**，AI 无法代收——这是硬阻断。
4. **支付**：走微信支付。不存在可编程代付路径。
5. **合规**：代人下单涉及用户身份、实名信息、真实资金。即便技术上打通，也属越权代理，**不做**。

**正确做法（推荐给用户的替代方案）**：
- 技能负责**选**：把目标团期（如「10-01 高阳山」）定位到具体 `batchId` / `dailyPkgId` / `batchPkgId`，核验余位（`memberCount / limitMax`）、状态（`status`）、成行门槛（`batchLimitDesc`）。
- 生成**直达下单页的链接**：`https://m.youxiake.com/lines/batch/orders?pid=<PID>&starttime=<批次首日10位时间戳>&did=<dailyPkgId>&batchPkgId=<batchPkgId>`，用户在微信里点开、自己登录、自己付款。
- 可用 `memberUrl` 字段直接取现成链接（v3 接口已返回）。
- 技能可做**下单前哨**：每场/提前盯余位，快满时提醒用户尽早报名。这部分是纯只读，完全可做。

## 9. 难度星级（必须走 `app/detail`）

**接口**：`GET /api/m/product/app/detail?pid=<PID>&oid=`
**路径**：`data.productOutdoorLevel` → `solidStarV2`（数字，可为 3.5/4.5 这种半星）、`levelTip`（等级名）、`starTitle`（"难度·野趣探险"）、`popupContent`（星级说明 HTML）。

⚠️ **同样是「详情接口」，只有 `app/detail` 有星级**：
- `/api/m/product/app/detail` ✅ 有 `productOutdoorLevel`
- `/api/m/product/lines/detail` ❌ 无（字段完全不存在，不是空）
- `/api/m/v2|v3/product/lines/detail` ❌ 404
→ 前端 `Line-LineDetail` 只调 `app/detail`，`lines/detail` 是另一套（PC/SEO 用）。**这是第二个「v2/v3 之外还有 app 版」的坑，与团期接口同理。**

**星级档位**（实测全量 34 条上海疾速线路）：

| 星级 | levelTip | 含义 | 典型活动 |
|---|---|---|---|
| 2 | 基础入门 | 轻量 | 无痕山野（捡垃圾公益线） |
| 2.5–3 | 野趣探险 | 中低强度，无需审核经验 | 徒步 10–15km + 爬升 500–1000m |
| 3.5–4 | 进阶挑战 | 中高强度 | — |
| 4.5–5 | 勇者征途 | 高强度/极限 | — |

**查询**：脚本已内置 `--min-star`：
```bash
$PY yxk.py search 疾速 --city 上海 --min-star 4        # 只看 4 星及以上
$PY yxk.py html 疾速 --city 上海 --min-star 4 -o out.html
```
⚠️ **不传 `--min-star` 时不会请求星级接口**（省每条线路 1 次请求），
因此 `search` 默认输出里 star 列显示「—」、`--json` 里 `star` 为 `null`。
**要拿到真实星级必须显式传 `--min-star`**（即使只想看全部也传个 `--min-star 0.1`）。
`html` 无此限制 —— 它总是拉取星级并给卡片加星级徽章，顶部还会出现「4★以上 N」筛选芯片。

⚠️ **快照键必须含 `--min-star`**：`snapshot_path()` 已把筛选条件并入文件名。否则 `--min-star 4` 与全量共用同一快照，diff 会误报大量「下架」（2026-09-30 踩到）。

**上海站 4★及以上线路（2026-09-30 实测 10 条）**：
5★ 远征大环线 / 侠野追风·远征大环；4.5★ 云石大环 / 吴中十峰 / 竹海秦望；4★ 九龙之巅 / 惠山一枝花 / 宜兴龙脊 / 福马线 / 炉峰七尖。
（注意：全标题含「4星天花板」的云石大环实为 4.5 星。）

## 10. 用户评价（2026-10-14 新增）

**接口**：`GET /api/m/product/lines/evaluation?pid=<PID>&page=<N>&sortName=&tagName=`
**无需登录**。返回 `data.{num, totalpage, pagesize, tags[], list[]}`，**每页 21 条，按时间倒序**。

**单条字段**：

| 字段 | 说明 |
|---|---|
| `username` / `avatar` / `uid` | 评价人 |
| `addtime` | 发表时间，**10 位秒级时间戳** |
| `content` | 正文，含 `</br>` 换行标签（需清洗） |
| `stars[]` | 分项评分：`class_type`（行程/司机/领队（1）…）+ `star`（"非常满意"）+ `color` |
| `totalityStar` | 总评星级（1–5） |
| `emotionContent` | 情绪标签，如 "棒极啦" |
| `quality` | **`1` = 平台精选**（会被置顶，可能是很久以前的）；`0` = 普通 |
| `startTime` | 出行时间，格式为 **"今年 10-11"**（非标准日期！老评价会是 "2024-09-28"） |
| `pkgname` | 套餐名，如 "上海出发·大巴往返" |
| `imageNum` / `imgs[]` | 图片数 / 图片列表（含 `url_xl/l/m` 多尺寸） |
| `likeNum` | 点赞数（**字符串**，需转换） |
| `reply` | 官方回复（空字符串表示无） |
| `pjId` / `oid` | 评价 id / 订单 id |

⚠️ **两个坑**：
1. **`quality == 1` 的精选评价被置顶**，其 `addtime` 可能是两年前 —— 直接取列表前 N 条会混入旧评价。
   **要「最近 N 条」必须按 `addtime` 排序，或跳过 `quality==1`**。
2. **`startTime` 是中文相对表述**（"今年 10-11"），不能当标准日期解析；需要绝对日期请结合 `addtime`。

**CLI（2026-10-14 新增 `reviews` 子命令）**：
```bash
$PY yxk.py reviews 39330                      # 最近 10 条（自动剔精选、按时间倒序）
$PY yxk.py reviews 39330 --limit 20           # 最近 20 条（自动跨页）
$PY yxk.py reviews 39330 --all                # 整页原始顺序（含精选置顶）
$PY yxk.py reviews --keyword 远征大环 --first  # 按关键词搜到再取第一条
$PY yxk.py reviews 39330 --json               # 机器可读
```

**接口定位方法（供后续扩展参考）**：与团期/星级同为「接口藏在 SPA chunk 里」模式 ——
1. 取移动端页面找 build 目录：`curl https://m.youxiake.com/lines.html?id=<PID>` → `/20261014095851/js/runtime.<hash>.js`
2. 下载 runtime，**名字表**与**hash 表**是两个相邻对象：名字表形如 `{"Line-ReviewList":"Line-ReviewList"}`，
   hash 表紧随其后形如 `{"Line-ReviewList":"25b3b228"}`（搜 `Activity-AnnualMeeting-2025-Menu` 定位起始）。
3. 拼 URL 下载：`https://m.youxiake.com/<build>/js/Line-ReviewList.<hash>.js`
4. chunk 里只有 UI，接口在 **`app.js`** 的 api 模块 —— 搜方法名 `getReviewList` 即得
   `this.get("product/lines/evaluation", {params:{pid, page, sortName, tagName}})`。
   （`get("xxx")` 的 `xxx` 即 `/api/m/` + 该路径）

**实测（2026-10-14）**：`疾速追山·远征大环线`(39330) 共 **3988 条评价 / 190 页**，
Top 标签：满分服务(63)、朋友式的旅行(58)、热情洋溢(57)、知识渊博(52)、鉴定为优秀领队(48)。
同名的 `侠野追风·远征大环`(60457) 仅 75 条 —— **两条线是不同产品，勿混**。

---

## 11. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| **1.1.1** | 2026-10-14 | **修复 3 个 bug**：① `leaders --json` 混入人类可读文本导致 JSON 无法解析；② `reviews --limit N`（N>100）被 `max_pages=5` 静默截断（请求 200 实收 104），改为按需翻页；③ `diff` 不支持 `--min-star`（与 `html` 不一致，快照键会串）。另修正 SKILL.md 第 0 节「疾速」易被误解为默认关键词、第 4 节正则缺 8 个前缀、第 9 节「默认输出已带星级」表述有误（实际须显式传 `--min-star`）。 |
| **1.1.0** | 2026-10-14 | 新增 **用户评价查询**（`reviews` 子命令 + 第 10 节）；`reviews` 补入第 0 节执行入口清单；移除全部个人绝对路径，改为通用写法（`python3` / `<技能目录>`），可跨机器运行。 |
| 1.0.0 | 2026-10-14 | 首个发布版：线路搜索 / 团期 / 领队 / 难度星级 / 变化对比 / HTML 清单生成。 |
