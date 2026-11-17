#!/usr/bin/env python3
"""生成游侠客线路清单的单文件 HTML（浅色、卡片、可筛选、支持按领队搜索）。

被 yxk.py 的 html 子命令调用：build(cards, out_path, ...)
数据以 `var DATA=[...]` 内联注入，可直接嵌入小程序 web-view。
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>游侠客 __CITY__站 · __TITLE__</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e6e8ec;--txt:#1c1f23;--sub:#6b7280;
--red:#d4342c;--green:#12855a;--amber:#b7791f;--blue:#1f6feb;--purple:#6b46c1}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:18px 14px 48px}
.hero{background:linear-gradient(135deg,#6b46c1,#1f6feb);border-radius:16px;padding:20px 18px;color:#fff}
.hero h1{margin:0 0 4px;font-size:19px;font-weight:700;letter-spacing:.3px}
.hero .meta{font-size:12.5px;opacity:.9}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}
.kpi{background:rgba(255,255,255,.16);border-radius:10px;padding:9px 10px}
.kpi b{display:block;font-size:19px;line-height:1.2;font-variant-numeric:tabular-nums}
.kpi span{font-size:11px;opacity:.88}
.sec-title{display:flex;align-items:center;gap:8px;margin:20px 2px 10px;font-size:13.5px;color:var(--sub)}
.sec-title::after{content:"";flex:1;height:1px;background:var(--line)}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{border:1px solid var(--line);background:#fff;color:var(--sub);border-radius:999px;
padding:5px 12px;font-size:12.5px;cursor:pointer}
.chip.on{background:var(--txt);color:#fff;border-color:var(--txt)}
input.search{flex:1;min-width:150px;border:1px solid var(--line);background:#fff;border-radius:10px;
padding:8px 12px;font-size:13.5px;color:var(--txt);outline:none}
input.search:focus{border-color:#9db8e8}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 15px;margin-bottom:10px}
.card.haslead{border-left:3px solid var(--purple);box-shadow:0 2px 10px rgba(107,70,193,.07)}
.card.none{border-left:3px solid #c9ccd1;opacity:.75}
.c-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.c-name{font-size:15.5px;font-weight:650;margin:0;line-height:1.35}
.c-name a{color:var(--txt);text-decoration:none}
.c-name a:hover{color:var(--blue)}
.badge{flex:none;font-size:11.5px;padding:3px 9px;border-radius:999px;font-weight:600;white-space:nowrap}
.badge.lead{background:#efe9fb;color:var(--purple)}
.badge.ok{background:#e6f6ee;color:var(--green)}
.badge.no{background:#f0f1f3;color:#8b9098}
.badge.seg{background:#eef3fb;color:#3d6bab;border:1px solid #cfdff5}
.badge.star{background:#eef3fb;color:#3a6ba8;border:1px solid #d3e2f5}
.badge.star.hot{background:#fdf0e6;color:#b4541d;border:1px solid #f6d5b8}
.c-line{display:flex;gap:12px;flex-wrap:wrap;font-size:12.5px;color:var(--sub);margin-top:6px}
.c-line i{font-style:normal;color:var(--txt);font-weight:600;font-variant-numeric:tabular-nums}
.bats{margin-top:10px;padding-top:10px;border-top:1px dashed var(--line);display:flex;flex-direction:column;gap:6px}
.bat{display:flex;align-items:center;gap:8px;font-size:12.5px;flex-wrap:wrap}
.bat .d{font-variant-numeric:tabular-nums;font-weight:600;min-width:78px}
.bat .p{color:var(--sub);min-width:44px;font-variant-numeric:tabular-nums}
.tag{font-size:11px;border-radius:6px;padding:2px 7px;background:#f4f6f8;border:1px solid var(--line);color:var(--sub)}
.tag.g{background:#eafaf2;border-color:#c5ebd9;color:var(--green)}
.tag.a{background:#fdf6e7;border-color:#f1dfae;color:var(--amber)}
.tag.f{background:#fdeceb;border-color:#f5c9c5;color:var(--red)}
.tag.seat{font-variant-numeric:tabular-nums}
.tag.seat i{font-style:normal;opacity:.55;margin-left:4px}
.tag.seat b{font-weight:600;margin-left:5px;padding:0 4px;border-radius:4px;background:var(--red);color:#fff;font-size:10px}
.tag.seat.near{background:#fdf6e7;border-color:#f1dfae;color:var(--amber)}
.tag.seat.over{background:#fdeceb;border-color:#f5c9c5;color:var(--red);font-weight:600}
.tag.org{background:#f0f4f9;border-color:#d5e0ec;color:#4a6785;font-weight:600}
.tag.org.alt{background:#eef3fb;border-color:#cfdff5;color:#3d6bab}
.leaders{display:flex;gap:5px;flex-wrap:wrap;margin-left:auto}
.lead{font-size:12px;background:#efe9fb;color:var(--purple);border:1px solid #ddd0f7;
border-radius:999px;padding:2px 9px;font-weight:600}
.lead.none{background:#f6f7f9;color:#a0a4ab;border-color:var(--line);font-weight:400}
.alts{margin-top:9px;font-size:12px;color:var(--sub)}
.alts a{color:var(--blue);text-decoration:none}
.daycard{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-bottom:10px}
.day-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap;padding-bottom:9px;margin-bottom:9px;border-bottom:1px solid var(--line)}
.day-d{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
.day-w{font-size:12px;color:var(--sub);background:#f4f6f8;border-radius:6px;padding:1px 6px}
.day-n{font-size:12px;color:var(--sub)}
.day-lead{font-size:11.5px;color:var(--purple);background:#efe9fb;border-radius:999px;padding:2px 9px;font-weight:600;margin-left:auto}
.row{display:flex;align-items:center;gap:8px;font-size:12.5px;flex-wrap:wrap;padding:5px 0;border-bottom:1px dashed #f0f1f3}
.row:last-child{border-bottom:0}
.row-name{font-weight:600;color:var(--txt);text-decoration:none;min-width:96px}
.row-name:hover{color:var(--blue)}
.row .p{color:var(--sub);font-variant-numeric:tabular-nums;min-width:44px}
.tip{margin-top:18px;font-size:12px;color:var(--sub);background:#fff;border:1px solid var(--line);
border-radius:12px;padding:12px 14px;line-height:1.75}
.tip b{color:var(--purple)}
.empty{text-align:center;color:var(--sub);padding:36px 0;font-size:13px}
@media (max-width:520px){.kpis{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>游侠客 · __CITY__站「__KEYWORD__」线路</h1>
    <div class="meta">__RANGE__ · 数据抓取于 __DATE__</div>
    <div class="kpis">
      <div class="kpi"><b id="kLines">0</b><span>线路</span></div>
      <div class="kpi"><b id="kOpen">0</b><span>开放团期</span></div>
      <div class="kpi"><b id="kLead">0</b><span>已派领队团期</span></div>
      <div class="kpi"><b id="kTotal">0</b><span>团期总数</span></div>
    </div>
  </div>

  <div class="sec-title">筛选</div>
  <div class="bar"><input class="search" id="q" placeholder="搜索线路名、领队名、集合点或日期"></div>
  <div class="chips" id="views"></div>
  <div class="chips" id="chips"></div>

  <div class="sec-title" id="listTitle">线路清单</div>
  <div id="list"></div>

  <div class="tip">
    <b>数据说明：</b><br>
    · 领队来自团期接口的 <code>servicePersonList</code>（<b>v3</b> 版才有）。<br>
    · 领队按<b>团期</b>分配，同线路不同日期领队不同，通常每期 2-4 名。<br>
    · 领队随排班推进出现，<b>与状态不严格绑定</b>（「可报名」也可能已派）；名单在出发前会持续调整。<br>
    · <b>蓝底集合点标签</b>区分同日同名团期：「主站」为默认集合点，其余为分站（浦东龙阳 / 宝山出发等）。<br>
    · 余位显示为 <code>已报/上限</code>；<b>红色「超售」</b>表示已报超出上限，<b>黄色</b>表示余位不足 15%。<br>
    · 「开放」= 可报名 或 确定成行；灰卡表示该时段暂无开放团期。<br>
    · 团期、余位与排班实时变动，下单前请以官网页面为准。
  </div>
</div>

<script>
var DATA=/*__DATA__*/;
var META=/*__META__*/;
function LBL(s){return s===3?"确定成行":s===1?"可报名":s===2?"名额暂满":"—";}
var state={q:"",filter:"all",view:"date"};
function stats(){
  var open=0,lead=0,total=0;
  DATA.forEach(function(c){c.batches.forEach(function(b){
    total++; if(b.status===1||b.status===3) open++; if(b.leads&&b.leads.length) lead++;
  });});
  return {lines:DATA.length,open:open,lead:lead,total:total};
}
function buildChips(){
  var s=stats();
  var hi=DATA.filter(function(c){return c.star!=null&&c.star>=4;}).length;
  var out=[
    {k:"all",t:"全部 "+s.lines},
    {k:"lead",t:"已派领队"},
    {k:"open",t:"有开放团期"}
  ];
  if(hi) out.splice(1,0,{k:"star4",t:"4★以上 "+hi});
  return out;
}
function renderChips(){
  document.getElementById("chips").innerHTML=buildChips().map(function(c){
    return '<div class="chip'+(state.filter===c.k?" on":"")+'" data-k="'+c.k+'">'+c.t+'</div>';
  }).join("");
  [].forEach.call(document.querySelectorAll(".chip"),function(el){
    el.onclick=function(){state.filter=el.dataset.k;render();};
  });
}
function match(c){
  if(state.q){
    var q=state.q,hit=c.name.indexOf(q)>=0
      ||(c.leaders||[]).some(function(l){return l.indexOf(q)>=0;})
      ||(c.batches||[]).some(function(b){
          return (b.date||"").indexOf(q)>=0 || (b.origin||"").indexOf(q)>=0;});
    if(!hit) return false;
  }
  if(state.filter==="lead"&&!c.leadBatchCount) return false;
  if(state.filter==="open"&&!c.openBatchCount) return false;
  if(state.filter==="star4"&&!(c.star!=null&&c.star>=4)) return false;
  return true;
}
function WD(d){
  var t=new Date(d+"T00:00:00");if(isNaN(t)) return "";
  return "日一二三四五六".charAt(t.getDay());
}
function leadHtml(b){
  return (b.leads&&b.leads.length)
    ?'<span class="leaders">'+b.leads.map(function(l){return '<span class="lead">'+l.name+'</span>';}).join("")+'</span>'
    :'<span class="leaders"><span class="lead none">领队未排</span></span>';
}
function originTag(b){
  if(!b.origin) return "";
  var main=(b.origin==="主站");
  return '<span class="tag org'+(main?"":" alt")+'">'+b.origin+'</span>';
}
function seatHtml(b){
  if(b.memberCount==null) return "";
  var lm=b.limitMax;
  if(lm==null||lm<=0) return '<span class="tag">'+b.memberCount+'人</span>';
  var pct=Math.round(b.memberCount/lm*100);
  var cls=pct>100?"over":(pct>=85?"near":"");
  var tip=cls==="over"?"超售":"";
  return '<span class="tag seat '+cls+'">'+b.memberCount+'/'+lm+'人'
    +'<i>'+pct+'%</i>'+(tip?'<b>'+tip+'</b>':'')+'</span>';
}
function tagsHtml(b){
  var cls=b.status===3?"a":b.status===1?"g":"";
  var fx=b.festival?'<span class="tag f">'+b.festival+'</span>':'';
  return '<span class="tag '+cls+'">'+LBL(b.status)+'</span>'+fx+seatHtml(b);
}
function starHtml(s,tip){
  return (s!=null)?'<span class="badge star'+(s>=4?" hot":"")+'">'
    +(s%1?s.toFixed(1):s)+'★'+(tip?" "+(tip||""):"")+'</span>':'';
}
function viewLines(rows){
  return rows.map(function(c){
    var bats=c.batches.map(function(b){
      return '<div class="bat"><span class="d">'+(b.date||"").slice(5)+'</span>'
        +'<span class="p">￥'+(b.price!=null?b.price:"—")+'</span>'
        +originTag(b)+tagsHtml(b)+leadHtml(b)+'</div>';
    }).join("");
    var badge=c.leadBatchCount
      ?'<span class="badge lead">已派领队 '+c.leadBatchCount+' 期</span>'
      :(c.openBatchCount?'<span class="badge ok">开放 '+c.openBatchCount+' 期</span>':'<span class="badge no">暂无开放</span>');
    var segBadge=(c.origins&&c.origins.length>1)
      ?'<span class="badge seg">'+c.origins.length+' 个集合点</span>':'';
    return '<div class="card '+(c.leadBatchCount?"haslead":(c.openBatchCount?"":"none"))+'">'
      +'<div class="c-top"><p class="c-name"><a href="'+c.url+'" target="_blank" rel="noopener">'+c.name+'</a></p>'
      +starHtml(c.star,c.levelTip)+segBadge+badge+'</div>'
      +'<div class="c-line"><span>起价 ￥<i>'+c.price+'</i></span><span>'+c.days+'</span>'
      +'<span>团期 <i>'+c.batches.length+'</i></span><span>已报名 <i>'+(c.registered||"—")+'</i></span></div>'
      +'<div class="bats">'+bats+'</div></div>';
  }).join("");
}
function viewDates(rows){
  var byDay={};
  rows.forEach(function(c){
    c.batches.forEach(function(b){
      var d=b.date||"—";
      (byDay[d]=byDay[d]||[]).push({c:c,b:b});
    });
  });
  var days=Object.keys(byDay).sort();
  if(!days.length) return '<div class="empty">没有符合条件的团期</div>';
  return days.map(function(d){
    var items=byDay[d],leadN=items.filter(function(x){return x.b.leads&&x.b.leads.length;}).length;
    var segs=new Set();
    items.forEach(function(x){if(x.b.segCount>1)segs.add(x.c.name);});
    var head='<div class="day-head"><span class="day-d">'+d.slice(5)+'</span>'
      +'<span class="day-w">周'+WD(d)+'</span>'
      +'<span class="day-n">'+items.length+' 条线路</span>'
      +(leadN?'<span class="day-lead">'+leadN+' 期已派领队</span>':'')
      +'</div>';
    var body=items.map(function(x){
      return '<div class="row"><a class="row-name" href="'+x.c.url+'" target="_blank" rel="noopener">'+x.c.name+'</a>'
        +starHtml(x.c.star,"")
        +originTag(x.b)
        +'<span class="p">￥'+(x.b.price!=null?x.b.price:x.c.price)+'</span>'
        +tagsHtml(x.b)+leadHtml(x.b)+'</div>';
    }).join("");
    return '<div class="daycard">'+head+body+'</div>';
  }).join("");
}
function render(){
  var s=stats();
  document.getElementById("kLines").textContent=s.lines;
  document.getElementById("kOpen").textContent=s.open;
  document.getElementById("kLead").textContent=s.lead;
  document.getElementById("kTotal").textContent=s.total;

  [].forEach.call(document.querySelectorAll("#views .chip"),function(el){
    el.className="chip"+(state.view===el.dataset.v?" on":"");
  });
  var rows=DATA.filter(match);
  if(!rows.length){document.getElementById("list").innerHTML='<div class="empty">没有符合条件的线路</div>';return;}
  document.getElementById("listTitle").textContent=state.view==="date"?"按日期":"按线路";
  document.getElementById("list").innerHTML=state.view==="date"?viewDates(rows):viewLines(rows);
}
function renderViews(){
  document.getElementById("views").innerHTML=[["date","按日期"],["line","按线路"]].map(function(v){
    return '<div class="chip'+(state.view===v[0]?" on":"")+'" data-v="'+v[0]+'">'+v[1]+'</div>';
  }).join("");
  [].forEach.call(document.querySelectorAll("#views .chip"),function(el){
    el.onclick=function(){state.view=el.dataset.v;render();};
  });
}
document.getElementById("q").oninput=function(e){state.q=e.target.value.trim();render();};
renderViews();renderChips();render();
</script>
</body>
</html>
"""


def build(cards: list[dict], out_path, *, city: str = "上海", keyword: str = "",
          start: str = "", end: str = "", record: int = 0) -> pathlib.Path:
    """把归并后的线路卡渲染成单文件 HTML。"""
    out_path = pathlib.Path(out_path)
    if start or end:
        rng = f"出发 {start or '不限'} ~ {end or '不限'}"
    else:
        rng = "全部可选日期"
    if record:
        rng += f"（站点共 {record} 条相关产品）"

    meta = {"city": city, "keyword": keyword, "start": start, "end": end,
            "generatedAt": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}

    html = (TEMPLATE
            .replace("/*__DATA__*/", json.dumps(cards, ensure_ascii=False, separators=(",", ":")))
            .replace("/*__META__*/", json.dumps(meta, ensure_ascii=False))
            .replace("__CITY__", city)
            .replace("__KEYWORD__", keyword)
            .replace("__RANGE__", rng)
            .replace("__TITLE__", keyword)
            .replace("__DATE__", meta["generatedAt"]))
    out_path.write_text(html, encoding="utf-8")
    _sanity_check(html, out_path)
    return out_path


def _sanity_check(html: str, out_path) -> None:
    """生成后自检：模板 JS 必须能被解析、DATA 必须能取出。

    背景（2026-10-12 事故）：改模板时多写了一个 `}`，浏览器 JS 直接抛
    SyntaxError，页面只渲染到「筛选」就空白 —— 而脚本仍报「已生成」，
    若不打开页面根本发现不了。故加这道自检，把关在生成阶段。
    """
    import re as _re
    m = _re.search(r"<script>(.*?)</script>", html, _re.S)
    if not m:
        raise RuntimeError(f"HTML 生成异常：找不到 <script> 块（{out_path}）")
    js = m.group(1)
    # 括号平衡（忽略字符串字面量内的括号影响：模板里字符串均已转义，足够用）
    for op, cl, nm in (("{", "}", "花括号"), ("(", ")", "圆括号"), ("[", "]", "方括号")):
        if js.count(op) != js.count(cl):
            raise RuntimeError(
                f"HTML 生成异常：JS {nm}不平衡 {js.count(op)} vs {js.count(cl)}"
                f"（{out_path}）—— 多半是模板改动多写/漏写了括号")
    if not _re.search(r"var\s+DATA\s*=\s*\[\s*\{", js):
        raise RuntimeError(f"HTML 生成异常：DATA 未注入或为空（{out_path}）")
    if "/*__DATA__*/" in html or "/*__META__*/" in html:
        raise RuntimeError(f"HTML 生成异常：模板占位符未替换干净（{out_path}）")
