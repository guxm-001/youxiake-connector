#!/usr/bin/env node
/**
 * 渲染自检：用内置 Chromium 真实加载生成的 HTML，确认页面完整渲染。
 *
 * 为什么需要它（2026-10-12 事故）：
 *   改 html_builder 模板时多写了一个 `}`，浏览器 JS 抛 SyntaxError，
 *   页面只渲染到「筛选」就一片空白，但 `yxk.py html` 仍打印「已生成」。
 *   用户截图反馈「没有数据啊」才发现。
 *   （注：Python 侧的 _sanity_check 已能拦括号不平衡，本脚本是更彻底的端到端验证。）
 *
 * 用法：
 *   node render_check.js <html路径>
 *
 *   依赖 playwright-core + 一个无头 Chromium。都没装也没关系 ——
 *   脚本会打印提示并以退出码 0 跳过（不影响主流程）。
 *   需要时自行准备：
 *     mkdir -p /tmp/yxk-deps && cd /tmp/yxk-deps
 *     npm i playwright-core
 *     npx playwright install chromium-headless-shell
 *     NODE_PATH=/tmp/yxk-deps/node_modules node render_check.js out.html
 *
 * 退出码 0 = 渲染正常（含 KPI/卡片/行数与 JS 零错误），或环境缺失被跳过；1 = 有问题。
 */
const path = require("path");
const fs = require("fs");

// 自动定位 playwright-core：依次尝试
//   1) 标准 require 解析（含 NODE_PATH）
//   2) 本脚本同级 node_modules
//   3) 常见临时安装位置 /tmp/yxk-deps
function loadPlaywright() {
  const candidates = [
    "playwright-core",
    path.join(__dirname, "node_modules", "playwright-core"),
    path.join(__dirname, "..", "node_modules", "playwright-core"),
    "/tmp/yxk-deps/node_modules/playwright-core",
  ];
  for (const c of candidates) {
    try {
      return require(c);
    } catch (_) {
      /* 继续试下一个 */
    }
  }
  return null;
}

// Chromium 版本号会随 playwright 升级变化，故自动探测 ms-playwright 下的实际目录。
function findChromium() {
  const bases = [
    path.join(process.env.HOME || "", "Library/Caches/ms-playwright"),
    path.join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of bases) {
    if (!base || !fs.existsSync(base)) continue;
    const dirs = fs.readdirSync(base)
      .filter((d) => d.startsWith("chromium_headless_shell-"))
      .sort()
      .reverse();
    for (const d of dirs) {
      for (const sub of [
        "chrome-headless-shell-mac-arm64",
        "chrome-headless-shell-mac-x64",
        "chrome-headless-shell-linux64",
        "chrome-headless-shell-win64",
      ]) {
        const exe = path.join(base, d, sub,
          sub.includes("win") ? "chrome-headless-shell.exe" : "chrome-headless-shell");
        if (fs.existsSync(exe)) return exe;
      }
    }
  }
  return null;
}

(async () => {
  const file = process.argv[2];
  if (!file) {
    console.error("用法: node render_check.js <html路径>");
    process.exit(1);
  }
  const pw = loadPlaywright();
  if (!pw) {
    console.error("⚠️ 未找到 playwright-core，跳过渲染自检（不影响交付）");
    console.error("   如需启用：npm i playwright-core && npx playwright install chromium-headless-shell");
    process.exit(0);
  }
  const exe = findChromium();
  if (!exe) {
    console.error("⚠️ 找不到 Chromium，跳过渲染自检（不影响交付）");
    process.exit(0);
  }
  const { chromium } = pw;
  const browser = await chromium.launch({ executablePath: exe });
  const page = await browser.newPage({ viewport: { width: 900, height: 1400 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push("CONSOLE: " + m.text());
  });
  await page.goto("file://" + path.resolve(file), { waitUntil: "load" });
  await page.waitForTimeout(700);

  const r = await page.evaluate(() => ({
    kLines: document.getElementById("kLines")?.textContent,
    kTotal: document.getElementById("kTotal")?.textContent,
    kLead: document.getElementById("kLead")?.textContent,
    daycards: document.querySelectorAll(".daycard").length,
    cards: document.querySelectorAll(".card").length,
    rows: document.querySelectorAll(".row").length,
    originTags: document.querySelectorAll(".tag.org").length,
    listLen: (document.getElementById("list")?.innerHTML || "").length,
  }));
  await browser.close();

  const total = Number(r.kTotal || 0);
  const rendered = r.daycards + r.cards;
  const problems = [];
  if (errors.length) problems.push("JS 报错: " + errors.join(" | "));
  if (listLen0(r)) problems.push("清单区为空（渲染中断）");
  if (total > 0 && rendered === 0) problems.push("KPI 有数据但未渲染任何卡片");

  console.log(JSON.stringify(r, null, 1));
  if (problems.length) {
    console.error("❌ 渲染自检未通过：\n  - " + problems.join("\n  - "));
    process.exit(1);
  }
  const detail = r.daycards
    ? r.daycards + " 张日期卡 + " + r.rows + " 行团期"
    : r.cards + " 张线路卡";
  console.log("✅ 渲染自检通过（" + total + " 期，" + detail + "，JS 零错误）");
})();

function listLen0(r) {
  return !r.rows && !r.cards && r.listLen < 50;
}
