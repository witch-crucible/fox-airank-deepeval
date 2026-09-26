// 鹈鹕骑自行车 · 自动化验证（Playwright + Chromium）
// 不以程序自报成功为准：所有结论来自页面内几何/DOM 测量与截图证据。
// 运行：npm run build && node public-test.mjs
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright";

const root = dirname(fileURLToPath(import.meta.url));
const shotDir = join(root, "verification");
mkdirSync(shotDir, { recursive: true });

const results = [];
async function check(name, fn) {
  try {
    await fn();
    results.push({ ok: true, name });
    console.log(`✓ ${name}`);
  } catch (err) {
    results.push({ ok: false, name, err: err.message });
    console.error(`✗ ${name}\n  ${String(err.message).split("\n").join("\n  ")}`);
  }
}

const browser = await chromium.launch().catch((err) => {
  console.error(`✗ 启动浏览器失败\n  ${err.message}`);
  console.log(`\n0/${results.length} 项通过，截图见 verification/`);
  process.exit(1);
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
try {
  await page.goto(pathToFileURL(join(root, "index.html")).href);
  await page.waitForFunction("window.pelican && document.body.dataset.ready === 'yes'", null, { timeout: 10000 });
} catch (err) {
  console.error(`✗ 页面加载失败\n  ${err.message}`);
  await browser.close();
  console.log(`\n0/${results.length} 项通过，截图见 verification/`);
  process.exit(1);
}

const seek = (t) => page.evaluate((tt) => window.pelican.seek(tt), t);
const snap = () => page.evaluate(() => window.pelican.snapshot());
const geom = () => page.evaluate(() => window.pelican.geometry());
const shot = (name) => page.screenshot({ path: join(shotDir, `${name}.png`) });

async function markerDist(a, b) {
  return page.evaluate(
    ([ia, ib]) => {
      const ea = document.getElementById(ia);
      const eb = document.getElementById(ib);
      if (!ea || !eb) return NaN;
      const ra = ea.getBoundingClientRect();
      const rb = eb.getBoundingClientRect();
      return Math.hypot(ra.x + ra.width / 2 - (rb.x + rb.width / 2), ra.y + ra.height / 2 - (rb.y + rb.height / 2));
    },
    [a, b],
  );
}

async function assertContacts(phase) {
  const dnFP = await markerDist("marker-foot-near", "marker-pedal-near");
  const dfFP = await markerDist("marker-foot-far", "marker-pedal-far");
  const dwg = await markerDist("marker-wing-tip", "marker-grip");
  assert.ok(Number.isFinite(dnFP), `${phase}: 接触标记缺失（marker-foot-near / marker-pedal-near）`);
  assert.ok(Number.isFinite(dfFP), `${phase}: 接触标记缺失（marker-foot-far / marker-pedal-far）`);
  assert.ok(Number.isFinite(dwg), `${phase}: 接触标记缺失（marker-wing-tip / marker-grip）`);
  assert.ok(dnFP <= 1.5, `${phase}: 近侧脚-踏板 DOM 距离 ${dnFP.toFixed(2)}px > 1.5px`);
  assert.ok(dfFP <= 1.5, `${phase}: 远侧脚-踏板 DOM 距离 ${dfFP.toFixed(2)}px > 1.5px`);
  assert.ok(dwg <= 1.5, `${phase}: 翅尖-车把 DOM 距离 ${dwg.toFixed(2)}px > 1.5px`);
  const g = await geom();
  assert.ok(!g.legNearClamped && !g.legFarClamped, `${phase}: 腿部 IK 被钳制，脚未真实到达踏板`);
  assert.ok(!g.wingClamped, `${phase}: 翅膀 IK 被钳制，翅尖未真实到达车把`);
}

// ===== 阶段 0：画布与朝向 =====
await check("画布 960×640，自行车朝右", async () => {
  const size = await page.evaluate(() => {
    const s = document.getElementById("stage");
    return { w: s.getAttribute("width"), h: s.getAttribute("height"), vb: s.getAttribute("viewBox") };
  });
  assert.equal(size.w, "960");
  assert.equal(size.h, "640");
  assert.equal(size.vb, "0 0 960 640");
  await seek(2.0);
  const g = await geom();
  assert.ok(g.beakTip.x > g.frontWheel.x, "喙尖应在前轮右侧（朝右）");
  assert.ok(g.frontWheel.x > g.rearWheel.x, "前轮应在后轮右侧");
  assert.ok(g.grip.x > g.frontWheel.x - 20, "车把应位于车头");
  await shot("00-cruise");
});

// ===== 阶段 1：正常骑行（车轮/曲柄/踏板/腿同步） =====
await check("阶段1 巡航：车轮-曲柄-踏板-腿同步", async () => {
  await seek(2.0);
  const s1 = await snap();
  assert.equal(s1.mode, "cruise");
  assert.ok(Math.abs(s1.v - 180) < 2, `巡航速度 ${s1.v}`);
  await seek(2.5);
  const s2 = await snap();
  // 滚动无滑移：轮转角 × 半径 ≡ 行进距离
  const d = s2.bikeX - s1.bikeX;
  assert.ok(d > 80, `0.5s 行进 ${d}px`);
  assert.ok(Math.abs((s2.wheelAngle - s1.wheelAngle) * 42 - d) < 1e-6, "车轮角位移×R ≠ 行进距离");
  // 曲柄与车轮固定齿比联动
  const ratio = (s2.crankAngle - s1.crankAngle) / (s2.wheelAngle - s1.wheelAngle);
  assert.ok(Math.abs(ratio - 42 / 16) < 1e-6, `曲柄/车轮角速度比 ${ratio}`);
  // 两踏板相位相反且都在做圆周运动
  await seek(2.0);
  const g1 = await geom();
  await seek(2.0833333);
  const g2 = await geom();
  assert.ok(Math.hypot(g2.pedalNear.x - g1.pedalNear.x, g2.pedalNear.y - g1.pedalNear.y) > 0.5, "踏板应在运动");
  assert.ok(Math.hypot(g1.pedalNear.x - g1.pedalFar.x, g1.pedalNear.y - g1.pedalFar.y) > 20, "两踏板应位于曲柄两端");
  await assertContacts("巡航");
  await shot("01-cruise-sync");
});

// ===== 全程不变量：0~23s 每 0.125s 检查脚-踏板 / 翅-车把刚性约束 =====
await check("全程约束：双脚始终在踏板上、翅膀始终扶把、车轮纯滚动", async () => {
  const bad = await page.evaluate(() => {
    const p = window.pelican;
    p.sim.reset();
    const out = [];
    const total = Math.round(23 / p.constants.DT);
    for (let i = 1; i <= total; i++) {
      p.sim.step(p.constants.DT);
      if (i % 15 !== 0) continue;
      const g = p.geometry();
      const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
      const t = +p.sim.t.toFixed(3);
      if (dist(g.footNear, g.pedalNear) > 1e-6) out.push(`t=${t} 近侧脚脱离踏板`);
      if (dist(g.footFar, g.pedalFar) > 1e-6) out.push(`t=${t} 远侧脚脱离踏板`);
      if (dist(g.wingTip, g.grip) > 1e-6) out.push(`t=${t} 翅尖脱离车把`);
      if (g.legNearClamped || g.legFarClamped || g.wingClamped) out.push(`t=${t} IK 钳制`);
      if (Math.abs(p.sim.wheelAngle * p.constants.WHEEL_R - p.sim.bikeX) > 1e-6) out.push(`t=${t} 车轮滑移`);
      if (p.sim.lift < -1e-9) out.push(`t=${t} lift<0`);
      if (p.sim.v < 0) out.push(`t=${t} v<0`);
    }
    return out.slice(0, 10);
  });
  assert.deepEqual(bad, [], `发现约束违规: ${JSON.stringify(bad)}`);
});

// ===== 阶段 2：接近石头前一刻（必须已减速） =====
await check("阶段2 接近石头：提前减速", async () => {
  await seek(5.5);
  let s = await snap();
  let stone = s.stones.find((x) => x.id.startsWith("stone-1"));
  assert.ok(stone, "stone-1 未生成");
  assert.ok(stone.gap > 60 && stone.gap < 300, `前轮距石 ${stone.gap}px 应在观察窗内`);
  assert.equal(s.mode, "approach");
  assert.ok(s.v < 180 * 0.8, `接近时速度 ${s.v} 未低于巡航的 80%`);
  // 一直减速到起跳前
  await seek(6.2);
  s = await snap();
  stone = s.stones.find((x) => x.id.startsWith("stone-1"));
  assert.ok(s.v <= 100, `起跳前速度 ${s.v}`);
  assert.ok(stone.gap > 0, "起跳前应尚未到石头");
  await shot("02-approach-stone");
});

// ===== 阶段 3：跃过石头（车轮高于石顶且 DOM 无重叠） =====
await check("阶段3 越过石头：跳跃轨迹高于石头且无碰撞", async () => {
  // 扫描找到前轮正好在石头上方的时刻
  let hit = null;
  for (let t = 6.4; t <= 8.0; t += 0.05) {
    await seek(t);
    const s = await snap();
    const stone = s.stones.find((x) => x.id.startsWith("stone-1"));
    if (s.mode === "hop" && stone && Math.abs(stone.gap) < 40) {
      hit = { t, s, stoneId: stone.id };
      break;
    }
  }
  assert.ok(hit, "未捕捉到跃过石头的时刻");
  assert.ok(hit.s.lift > 26, `跃起高度 ${hit.s.lift}px 应大于石头高 26px`);
  const overlap = await page.evaluate((entId) => {
    const a = document.getElementById("wheel-front").getBoundingClientRect();
    const b = document.getElementById(entId);
    if (!b) return { err: "石头节点不存在" };
    const bb = b.getBoundingClientRect();
    return {
      overlap: !(a.right < bb.left || bb.right < a.left || a.bottom < bb.top || bb.bottom < a.top),
      wheelBottom: a.bottom,
      stoneTop: bb.top,
    };
  }, `ent-${hit.stoneId}`);
  assert.ok(!overlap.err, overlap.err);
  assert.ok(!overlap.overlap, `前轮 bbox 底 ${overlap.wheelBottom} 与石头顶 ${overlap.stoneTop} 重叠`);
  await assertContacts("跃障中");
  await shot("03-hop-stone");
});

// ===== 阶段 4：坠落物轨迹可测 + 刹车停让 =====
await check("阶段4 坠落物：二次轨迹可测（拟合 g≈340）", async () => {
  const samples = [];
  for (const t of [8.7, 8.9, 9.1]) {
    await seek(t);
    const s = await snap();
    const d = s.drops.find((x) => x.id.startsWith("drop-1"));
    assert.ok(d, `t=${t} drop-1 未生成`);
    assert.ok(!d.landed, `t=${t} 尚未落地`);
    samples.push({ t, alt: d.alt, screenY: d.screenY });
  }
  const dt = 0.2;
  const acc = (samples[2].alt - 2 * samples[1].alt + samples[0].alt) / (dt * dt);
  assert.ok(Math.abs(acc + 340) < 10, `实测加速度 ${acc.toFixed(1)} px/s²，应≈ -340`);
  const v01 = (samples[1].alt - samples[0].alt) / dt;
  const v12 = (samples[2].alt - samples[1].alt) / dt;
  assert.ok(v01 < 0 && v12 < v01, "应持续加速下落");
  // 屏幕 y 与高度一致（可测量的下落轨迹贯穿渲染层）
  assert.ok(Math.abs(samples[0].screenY - (540 - samples[0].alt)) < 0.01, "screenY ≠ GROUND_Y - alt");
});

await check("阶段4 坠落物：鹈鹕刹车并在落点前停住", async () => {
  await seek(10.15);
  let s = await snap();
  assert.ok(s.mode === "brake" || s.mode === "stopped", `t=10.15 模式 ${s.mode} 应为刹车/停车`);
  assert.ok(s.v <= 90, `刹车中速度 ${s.v} 应已降至巡航一半以下`);
  const d = s.drops.find((x) => x.id.startsWith("drop-1"));
  assert.ok(d, "drop-1 不存在");
  assert.ok(s.frontX < d.x - 80, `前轮 ${s.frontX} 距落点 ${d.x} 不足 80px`);
  await shot("04-brake-drop");

  await seek(10.45);
  s = await snap();
  assert.equal(s.mode, "stopped", "掉落物落地时鹈鹕应已停住");
  assert.equal(s.v, 0);
  const d2 = s.drops.find((x) => x.id.startsWith("drop-1"));
  assert.ok(d2, "drop-1 不存在");
  assert.ok(d2.landed, "掉落物应已落地");
  assert.ok(s.frontX <= d2.x - 110 + 1, `停车位置 ${s.frontX} 超出安全线 ${d2.x - 110}`);
  await assertContacts("停车避让");
  await shot("05-stopped-drop");
});

// ===== 阶段 5：组合事件（石头 + 坠落物同时处理） =====
await check("阶段5 组合事件：石头与坠落物同时在场，系统停车兼顾两者", async () => {
  await seek(18.5);
  const s = await snap();
  const stone = s.stones.find((x) => x.id.startsWith("stone-2"));
  const drop = s.drops.find((x) => x.id.startsWith("drop-2"));
  assert.ok(stone && stone.gap > 0, "组合阶段石头应在前方");
  assert.ok(drop && !drop.gone, "组合阶段坠落物应仍在场");
  assert.ok(drop.x > stone.x, "坠落物落点应在石头更前方");
  assert.equal(s.mode, "stopped", `组合阶段模式 ${s.mode} 应为停车等待`);
  assert.equal(s.v, 0);
  assert.ok(s.frontX < stone.x, `停车位置应在石头之前（front ${s.frontX} < stone ${stone.x}）`);
  assert.ok(s.frontX <= drop.x - 110 + 1, "停车位置应在坠落物安全线内");
  assert.ok(stone.gap < 300, "停车点应紧贴石头，说明同时考虑了两个障碍");
  await assertContacts("组合事件");
  await shot("06-combo-stopped");

  // 坠落物消失后立即接续跃过石头：两个事件顺序处理且约束不破
  await seek(21.0);
  const s2 = await snap();
  assert.equal(s2.mode, "hop", `t=21 应正在跃过 stone-2，实际 ${s2.mode}`);
  assert.ok(s2.lift > 26, "组合后跃起高度不足");
  await assertContacts("组合后跃障");
  await shot("07-combo-hop");
});

// ===== 阶段 6：事件结束恢复骑行 =====
await check("阶段6 恢复骑行：回到巡航速度且约束完好", async () => {
  await seek(22.9);
  const s = await snap();
  assert.equal(s.mode, "cruise", `模式 ${s.mode}`);
  assert.ok(Math.abs(s.v - 180) < 2, `速度 ${s.v}`);
  assert.equal(s.stones.filter((x) => x.gap > 0 && x.gap < 400).length, 0, "前方不应再有石头");
  assert.equal(s.drops.filter((x) => !x.gone && x.gap > 0 && x.gap < 700).length, 0, "前方不应再有坠落物");
  await assertContacts("恢复骑行");
  await shot("08-recovered");
});

// ===== 页面错误 =====
await check("无未捕获页面错误", async () => {
  assert.deepEqual(errors, []);
});

await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} 项通过，截图见 verification/`);
if (failed.length) {
  console.error("失败项：");
  for (const f of failed) console.error(` - ${f.name}: ${f.err.split("\n")[0]}`);
  process.exit(1);
}
console.log("public test passed");
