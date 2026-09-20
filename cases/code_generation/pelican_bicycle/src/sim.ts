// ===== 纯仿真核心：无 DOM 依赖，固定步长确定性推进 =====
// 世界坐标：x 向右增长，高度 alt 以地面为 0、向上为正。
// 车身局部坐标：原点在前后轮触地点之间的地面处，y 向下为负值向上（SVG 习惯）。

type Mode = "cruise" | "approach" | "hop" | "land" | "brake" | "stopped" | "resume";

interface StoneEntity {
  kind: "stone";
  id: string;
  x: number; // 石头中心的世界坐标
  w: number;
  h: number;
}

interface DropEntity {
  kind: "drop";
  id: string;
  x: number; // 坠落线的世界坐标
  alt0: number; // 初始高度（px，地面以上）
  v0: number; // 初始向下速度（px/s）
  g: number; // 重力加速度（px/s^2）
  r: number; // 半径
  spawnTime: number; // 出场仿真时刻
  tau: number; // 出场后经过的秒数
  alt: number; // 当前高度
  landed: boolean;
  landTime: number; // 实际落地时刻（解析解）
  predictedLandTime: number;
  gone: boolean; // 落地后碎裂消失
  goneTime: number;
}

type Entity = StoneEntity | DropEntity;

interface ScenarioEvent {
  id: string;
  at: number; // 本周期内的触发时刻
  cycle: number; // 已触发的周期数
  lead: number; // 周期 >0 时相对骑手前方生成
  spawn: () => Entity;
}

interface Pt {
  x: number;
  y: number;
}

// ----- 常量 -----
const DT = 1 / 120; // 固定仿真步长
const VIEW_W = 960;
const VIEW_H = 640;
const GROUND_Y = 540; // 地面屏幕 y
const BIKE_SCREEN_X = 300; // 骑手固定屏幕 x

const WHEEL_R = 42;
const FRONT_OFFSET = 78; // 前轮中心相对车身原点
const REAR_OFFSET = -60;
const CRANK_ARM = 15;
const CRANK_K = 1 / 16; // 曲柄角速度系数 rad/px

const CRUISE_SPEED = 180;
const ACCEL = 140;
const APPROACH_DECEL = 160;
const APPROACH_MIN = 95;
const BRAKE_DECEL = 300;
const STONE_LOOKAHEAD = 300;
const STONE_STOP_GAP = 130; // 因掉落物停车时与前石的最小间距
const HOP_TRIGGER_GAP = 90; // 前轮距石多近起跳
const HOP_H = 52;
const HOP_LEN = 280; // 起跳到落地的水平行程
const HOP_RAMP = 70; // 上升/下降段长度
const HOP_TARGET = 140;
const HOP_ACCEL = 160;
const SAFE_GAP = 110; // 停车后前轮到落点的安全距离
const LAND_HOLD = 0.7; // 落地后停留时间
const DROP_GONE_DELAY = 0.7;
const CYCLE_T = 24; // 场景循环周期

// 车身局部几何（y 向下为正，向上为负）
const GEO = {
  rearWheel: { x: REAR_OFFSET, y: -WHEEL_R },
  frontWheel: { x: FRONT_OFFSET, y: -WHEEL_R },
  crank: { x: 4, y: -46 },
  hip: { x: -30, y: -126 }, // 近侧腿髋关节
  hipFar: { x: -25, y: -128 }, // 远侧腿髋关节（视觉错位）
  thigh: 52,
  shin: 56,
  shoulder: { x: -2, y: -172 },
  upperArm: 48,
  foreArm: 46,
  grip: { x: 72, y: -134 }, // 车把握持点
  neckBase: { x: 10, y: -168 },
  head: { x: 34, y: -208 },
  beakTip: { x: 112, y: -198 },
  seat: { x: -36, y: -126 },
  headTubeTop: { x: 64, y: -116 },
};

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

function smoothstep(u: number): number {
  const t = clamp(u, 0, 1);
  return t * t * (3 - 2 * t);
}

// 两骨段 IK：返回关节点；bend=-1 时关节偏向目标方向线的上方/前侧。
function ik2(
  hip: Pt,
  target: Pt,
  l1: number,
  l2: number,
  bend: number,
): { joint: Pt; target: Pt; clamped: boolean } {
  const dx = target.x - hip.x;
  const dy = target.y - hip.y;
  let d = Math.hypot(dx, dy);
  let clamped = false;
  const maxD = l1 + l2 - 0.5;
  const minD = Math.abs(l1 - l2) + 0.5;
  let tx = target.x;
  let ty = target.y;
  if (d > maxD || d < minD) {
    clamped = true;
    const nd = clamp(d, minD, maxD);
    const s = d === 0 ? 0 : nd / d;
    tx = hip.x + dx * s;
    ty = hip.y + dy * s;
    d = nd;
  }
  const a = Math.atan2(ty - hip.y, tx - hip.x);
  const cosA = clamp((d * d + l1 * l1 - l2 * l2) / (2 * d * l1), -1, 1);
  const ang = Math.acos(cosA);
  const ja = a + bend * ang;
  return {
    joint: { x: hip.x + l1 * Math.cos(ja), y: hip.y + l1 * Math.sin(ja) },
    target: { x: tx, y: ty },
    clamped,
  };
}

function rotatePt(p: Pt, pivot: Pt, rad: number): Pt {
  const c = Math.cos(rad);
  const s = Math.sin(rad);
  const dx = p.x - pivot.x;
  const dy = p.y - pivot.y;
  return { x: pivot.x + dx * c - dy * s, y: pivot.y + dx * s + dy * c };
}

class EventScheduler {
  events: ScenarioEvent[] = [];

  addStone(id: string, at: number, x: number, w: number, h: number): void {
    this.events.push({
      id,
      at,
      cycle: 0,
      lead: x,
      spawn: () => ({ kind: "stone", id: `${id}#${this.cycleOf(id)}`, x, w, h }),
    });
  }

  addDrop(id: string, at: number, x: number, alt0: number, v0: number, g: number, r: number): void {
    this.events.push({
      id,
      at,
      cycle: 0,
      lead: x,
      spawn: () => makeDrop(`${id}#${this.cycleOf(id)}`, x, alt0, v0, g, r, -1),
    });
  }

  cycleOf(id: string): number {
    const ev = this.events.find((e) => e.id === id);
    return ev ? ev.cycle - 1 : 0;
  }

  update(t: number, bikeX: number, out: Entity[]): string[] {
    const fired: string[] = [];
    for (const ev of this.events) {
      while (t >= ev.at + ev.cycle * CYCLE_T) {
        const k = ev.cycle;
        ev.cycle += 1;
        if (k === 0) {
          out.push(ev.spawn());
        } else {
          // 循环周期：按骑手当前位置生成在前方，保持相对布局
          const base = ev.lead;
          const shifted = bikeX + 900 + (base - 1150);
          const e = ev.spawn();
          e.x = shifted;
          out.push(e);
        }
        fired.push(ev.id);
      }
    }
    return fired;
  }
}

function makeDrop(
  id: string,
  x: number,
  alt0: number,
  v0: number,
  g: number,
  r: number,
  spawnTime: number,
): DropEntity {
  const disc = v0 * v0 + 2 * g * (alt0 - r);
  const tauLand = disc > 0 ? (-v0 + Math.sqrt(disc)) / g : 0;
  return {
    kind: "drop",
    id,
    x,
    alt0,
    v0,
    g,
    r,
    spawnTime,
    tau: 0,
    alt: alt0,
    landed: false,
    landTime: spawnTime >= 0 ? spawnTime + tauLand : -1,
    predictedLandTime: spawnTime >= 0 ? spawnTime + tauLand : -1,
    gone: false,
    goneTime: -1,
  };
}

class Simulation {
  t = 0;
  bikeX = 0;
  v = CRUISE_SPEED;
  mode: Mode = "cruise";
  lift = 0;
  stopReason: "drop" | null = null;
  entities: Entity[] = [];
  scheduler = new EventScheduler();
  firedLog: { id: string; t: number }[] = [];
  headAim = 0; // 0 平视，1 抬头看向坠落物
  lean = 0; // 上身后仰（刹车/停车时）
  private hopStartX = 0;
  private hopStoneId = "";
  private stoneSeq = 0;
  private dropSeq = 0;

  constructor() {
    this.buildScenario();
    this.reset();
  }

  private buildScenario(): void {
    const s = this.scheduler;
    // 阶段 1：单石头（减速 + 跃过）
    s.addStone("stone-1", 0.0, 1150, 44, 26);
    // 阶段 2：单掉落物（可测轨迹 + 刹车停让）
    s.addDrop("drop-1", 8.5, 1750, 420, 20, 340, 13);
    // 阶段 3：组合事件（石头在前，坠落物落在更前方）
    s.addStone("stone-2", 12.0, 2900, 44, 26);
    s.addDrop("drop-2", 17.0, 3200, 420, 20, 340, 13);
  }

  reset(): void {
    this.t = 0;
    this.bikeX = 0;
    this.v = CRUISE_SPEED;
    this.mode = "cruise";
    this.lift = 0;
    this.stopReason = null;
    this.entities = [];
    this.firedLog = [];
    this.headAim = 0;
    this.lean = 0;
    this.hopStartX = 0;
    this.hopStoneId = "";
    this.stoneSeq = 0;
    this.dropSeq = 0;
    for (const ev of this.scheduler.events) ev.cycle = 0;
  }

  get frontX(): number {
    return this.bikeX + FRONT_OFFSET;
  }

  get wheelAngle(): number {
    return this.bikeX / WHEEL_R;
  }

  get crankAngle(): number {
    return this.bikeX * CRANK_K;
  }

  stones(): StoneEntity[] {
    return this.entities.filter((e): e is StoneEntity => e.kind === "stone");
  }

  drops(): DropEntity[] {
    return this.entities.filter((e): e is DropEntity => e.kind === "drop");
  }

  // 威胁中的掉落物：未消失、落点在前方、距离可反应
  threatDrops(): DropEntity[] {
    return this.drops().filter((d) => !d.gone && d.x - this.frontX > -10 && d.x - this.frontX < 700);
  }

  // 需要处理的石头：在前方视野内
  threatStones(): StoneEntity[] {
    return this
      .stones()
      .filter((s) => s.id !== this.hopStoneId && s.x - this.frontX > -20 && s.x - this.frontX < STONE_LOOKAHEAD + 40)
      .sort((a, b) => a.x - b.x);
  }

  step(dt: number): void {
    // 1) 统一调度器：按时间线生成实体
    const fired = this.scheduler.update(this.t, this.bikeX, this.entities);
    for (const id of fired) {
      this.firedLog.push({ id, t: this.t });
      const spawned = this.entities[this.entities.length - 1];
      if (spawned && spawned.kind === "drop") spawned.spawnTime = this.t;
      if (spawned && spawned.kind === "drop") {
        const d = spawned;
        const disc = d.v0 * d.v0 + 2 * d.g * (d.alt0 - d.r);
        const tauLand = disc > 0 ? (-d.v0 + Math.sqrt(disc)) / d.g : 0;
        d.landTime = this.t + tauLand;
        d.predictedLandTime = d.landTime;
      }
      if (id.startsWith("stone")) this.stoneSeq += 1;
      if (id.startsWith("drop")) this.dropSeq += 1;
    }

    // 2) 掉落物运动学：闭式轨迹 alt(τ) = alt0 - v0·τ - ½·g·τ²
    for (const d of this.drops()) {
      if (d.spawnTime < 0) d.spawnTime = this.t;
      d.tau = Math.max(0, this.t - d.spawnTime);
      if (!d.landed) {
        d.alt = d.alt0 - d.v0 * d.tau - 0.5 * d.g * d.tau * d.tau;
        if (d.alt <= d.r) {
          d.alt = d.r;
          d.landed = true;
          if (d.landTime < 0) d.landTime = this.t;
        }
      }
      if (d.landed && !d.gone && this.t >= d.landTime + DROP_GONE_DELAY) {
        d.gone = true;
        d.goneTime = this.t;
      }
    }

    // 3) 模式状态机
    this.updateMode(dt);

    // 4) 积分速度 / 位置
    this.bikeX += this.v * dt;

    // 5) 跃障高度（距离驱动的梯形弧线）
    if (this.mode === "hop") {
      const s = this.bikeX - this.hopStartX;
      if (s < HOP_RAMP) this.lift = HOP_H * smoothstep(s / HOP_RAMP);
      else if (s > HOP_LEN - HOP_RAMP) this.lift = HOP_H * smoothstep((HOP_LEN - s) / HOP_RAMP);
      else this.lift = HOP_H;
    } else if (this.mode !== "land") {
      this.lift = 0;
    } else {
      this.lift = 0;
    }

    // 6) 姿态平滑（抬头看坠落物 / 刹车后仰）
    const aimTarget = this.threatDrops().some((d) => !d.landed) ? 1 : 0;
    this.headAim += (aimTarget - this.headAim) * Math.min(1, dt * 6);
    const leanTarget = this.mode === "brake" || this.mode === "stopped" ? -0.1 : 0;
    this.lean += (leanTarget - this.lean) * Math.min(1, dt * 6);

    this.t += dt;

    // 7) 清理远离的实体
    if (this.entities.length > 24) {
      this.entities = this.entities.filter((e) => e.x > this.bikeX - 800 && !(e.kind === "drop" && e.gone && this.t - e.goneTime > 1));
    }
  }

  private stopDist(v: number): number {
    return (v * v) / (2 * BRAKE_DECEL);
  }

  private updateMode(dt: number): void {
    const threats = this.threatDrops();
    // 因掉落物需要的停车线（自行车原点坐标）
    let dropStopX = Infinity;
    for (const d of threats) {
      if (d.landTime >= this.t || (d.landed && this.t < d.landTime + DROP_GONE_DELAY)) {
        dropStopX = Math.min(dropStopX, d.x - SAFE_GAP - FRONT_OFFSET);
      }
    }
    const stones = this.threatStones();
    let stoneStopX = Infinity;
    for (const s of stones) stoneStopX = Math.min(stoneStopX, s.x - STONE_STOP_GAP - FRONT_OFFSET);

    switch (this.mode) {
      case "hop": {
        this.v = Math.min(this.v + HOP_ACCEL * dt, HOP_TARGET);
        if (this.bikeX - this.hopStartX >= HOP_LEN) {
          this.mode = "land";
          this.lift = 0;
          this.hopStoneId = "";
        }
        return;
      }
      case "brake": {
        const target = this.brakeTarget;
        this.v = Math.max(0, this.v - BRAKE_DECEL * dt);
        if (this.v <= 0 || (target !== null && this.bikeX >= target)) {
          this.v = 0;
          if (target !== null) this.bikeX = Math.min(this.bikeX, target);
          this.mode = "stopped";
        }
        return;
      }
      case "stopped": {
        this.v = 0;
        let release = 0;
        for (const d of this.threatDrops()) {
          if (!d.gone) release = Math.max(release, d.landTime + DROP_GONE_DELAY);
        }
        if (this.t >= release) {
          this.mode = "resume";
          this.stopReason = null;
        }
        return;
      }
      default:
        break;
    }

    // cruise / approach / land / resume：统一决策
    // 优先级 1：坠落物停车（组合事件时停车线同时受前方石头约束）
    if (dropStopX < Infinity) {
      const stopX = Math.min(dropStopX, stoneStopX);
      if (stopX - this.bikeX <= this.stopDist(this.v) + 20 && stopX > this.bikeX - 4) {
        this.mode = "brake";
        this.stopReason = "drop";
        this.brakeTarget = stopX;
        this.v = Math.max(0, this.v - BRAKE_DECEL * dt);
        return;
      }
    }
    // 优先级 2：石头 —— 近距起跳跃过，远距减速接近
    if (stones.length > 0) {
      const s = stones[0];
      const gap = s.x - this.frontX;
      if (gap <= HOP_TRIGGER_GAP && gap > -20) {
        this.mode = "hop";
        this.hopStartX = this.bikeX;
        this.hopStoneId = s.id;
        this.lift = 0;
        return;
      }
      this.mode = "approach";
      if (this.v > APPROACH_MIN) this.v = Math.max(APPROACH_MIN, this.v - APPROACH_DECEL * dt);
      else this.v = Math.min(APPROACH_MIN, this.v + ACCEL * dt);
      return;
    }
    // 优先级 3：恢复巡航
    this.mode = this.v >= CRUISE_SPEED - 0.5 ? "cruise" : this.mode === "land" || this.mode === "resume" ? "resume" : "cruise";
    this.v = Math.min(CRUISE_SPEED, this.v + ACCEL * dt);
    if (this.v >= CRUISE_SPEED - 0.01) this.mode = "cruise";
  }

  private brakeTarget: number | null = null;

  // ----- 供渲染与验证使用的几何 -----
  pedalPos(phase: number): Pt {
    const a = this.crankAngle + phase;
    return { x: GEO.crank.x + CRANK_ARM * Math.cos(a), y: GEO.crank.y + CRANK_ARM * Math.sin(a) };
  }

  legIK(hipLocal: Pt, pedal: Pt, bend: number) {
    return ik2(hipLocal, pedal, GEO.thigh, GEO.shin, bend);
  }

  // 上身后仰时肩点绕髋旋转，翅膀 IK 仍精确落在握把上
  shoulderPos(): Pt {
    return rotatePt(GEO.shoulder, GEO.hip, this.lean);
  }

  wingIK() {
    return ik2(this.shoulderPos(), GEO.grip, GEO.upperArm, GEO.foreArm, -1);
  }

  localToScreen(p: Pt): Pt {
    return { x: BIKE_SCREEN_X + p.x, y: GROUND_Y - this.lift + p.y };
  }

  snapshot() {
    return {
      t: this.t,
      bikeX: this.bikeX,
      frontX: this.frontX,
      v: this.v,
      mode: this.mode,
      lift: this.lift,
      stopReason: this.stopReason,
      wheelAngle: this.wheelAngle,
      crankAngle: this.crankAngle,
      headAim: this.headAim,
      lean: this.lean,
      fired: this.firedLog.slice(),
      stones: this.stones().map((s) => ({ id: s.id, x: s.x, w: s.w, h: s.h, screenX: s.x - this.bikeX + BIKE_SCREEN_X, gap: s.x - this.frontX })),
      drops: this.drops().map((d) => ({
        id: d.id,
        x: d.x,
        alt: d.alt,
        tau: d.tau,
        alt0: d.alt0,
        v0: d.v0,
        g: d.g,
        r: d.r,
        spawnTime: d.spawnTime,
        landed: d.landed,
        landTime: d.landTime,
        gone: d.gone,
        screenX: d.x - this.bikeX + BIKE_SCREEN_X,
        screenY: GROUND_Y - d.alt,
        gap: d.x - this.frontX,
      })),
    };
  }

  geometry() {
    const pedalNear = this.pedalPos(0);
    const pedalFar = this.pedalPos(Math.PI);
    const legNear = this.legIK(GEO.hip, pedalNear, -1);
    const legFar = this.legIK(GEO.hipFar, pedalFar, -1);
    const wing = this.wingIK();
    const scr = (p: Pt) => this.localToScreen(p);
    return {
      pedalNear: scr(pedalNear),
      pedalFar: scr(pedalFar),
      footNear: scr(legNear.target),
      footFar: scr(legFar.target),
      kneeNear: scr(legNear.joint),
      kneeFar: scr(legFar.joint),
      legNearClamped: legNear.clamped,
      legFarClamped: legFar.clamped,
      wingTip: scr(wing.target),
      wingElbow: scr(wing.joint),
      wingClamped: wing.clamped,
      grip: scr(GEO.grip),
      shoulder: scr(this.shoulderPos()),
      beakTip: scr(rotatePt(GEO.beakTip, GEO.neckBase, -0.32 * this.headAim)),
      frontWheel: { ...scr(GEO.frontWheel), r: WHEEL_R },
      rearWheel: { ...scr(GEO.rearWheel), r: WHEEL_R },
      wheelBottomY: GROUND_Y - this.lift,
    };
  }
}
