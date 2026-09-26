// ===== SVG 渲染器：根据仿真状态绘制场景（全部图形由代码生成，无外部素材） =====

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag: string, attrs: Record<string, string | number | undefined>, parent?: Element): SVGElement {
  const el = document.createElementNS(SVG_NS, tag);
  for (const k of Object.keys(attrs)) {
    const v = attrs[k];
    if (v === undefined || v === null) continue;
    el.setAttribute(k, String(v));
  }
  if (parent) parent.appendChild(el);
  return el;
}

function setA(el: Element | null | undefined, name: string, value: string | number): void {
  if (el) el.setAttribute(name, String(value));
}

const INK = "#41382e";
const BODY_FILL = "#f7f2e7";
const BODY_SHADE = "#d8cfbe";
const BEAK = "#f0a541";
const POUCH = "#f7c96b";
const LEG = "#e8a33d";
const LEG_FAR = "#c08a35";
const FRAME = "#b0432e";
const TIRE = "#31302e";

const MODE_ZH: Record<Mode, string> = {
  cruise: "巡航",
  approach: "接近石头·减速",
  hop: "跃过石头",
  land: "落地加速",
  brake: "紧急刹车",
  stopped: "停车避让",
  resume: "恢复骑行",
};

class Renderer {
  svg: SVGSVGElement;
  private sim: Simulation;
  private refs: Record<string, SVGElement> = {};
  private stoneNodes = new Map<string, SVGGElement>();
  private dropNodes = new Map<string, SVGGElement>();
  private worldLayer!: SVGGElement;
  private bikeGroup!: SVGGElement;
  private hudMode!: SVGTextElement;
  private hudInfo!: SVGTextElement;
  private shadow!: SVGEllipseElement;
  private clouds: SVGGElement[] = [];
  private hills: SVGGElement[] = [];
  private stripes: SVGGElement[] = [];
  private pouch!: SVGPathElement;
  private headGroup!: SVGGElement;
  private upperGroup!: SVGGElement;
  private wingFar!: SVGGElement;
  private spinRear: SVGGElement | null = null;
  private spinFront: SVGGElement | null = null;
  private trailNodes = new Map<string, SVGGElement>();
  private dustNodes = new Map<string, SVGGElement>();

  constructor(svg: SVGSVGElement, sim: Simulation) {
    this.svg = svg;
    this.sim = sim;
    this.build();
  }

  private build(): void {
    const svg = this.svg;
    svg.setAttribute("viewBox", `0 0 ${VIEW_W} ${VIEW_H}`);
    svg.setAttribute("width", String(VIEW_W));
    svg.setAttribute("height", String(VIEW_H));

    // 天空
    const defs = svgEl("defs", {}, svg) as SVGDefsElement;
    const sky = svgEl("linearGradient", { id: "sky", x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    svgEl("stop", { offset: "0%", "stop-color": "#bfe3f2" }, sky);
    svgEl("stop", { offset: "100%", "stop-color": "#eaf6f8" }, sky);
    svgEl("rect", { x: 0, y: 0, width: VIEW_W, height: GROUND_Y, fill: "url(#sky)" }, svg);
    // 太阳
    svgEl("circle", { cx: 850, cy: 90, r: 38, fill: "#ffd98a" }, svg);
    svgEl("circle", { cx: 850, cy: 90, r: 30, fill: "#ffe9b0" }, svg);

    // 云（视差 0.15）
    const cloudLayer = svgEl("g", { id: "clouds" }, svg);
    for (let i = 0; i < 3; i++) {
      const c = svgEl("g", {}, cloudLayer) as SVGGElement;
      const s = 0.8 + i * 0.25;
      svgEl("ellipse", { cx: 0, cy: 0, rx: 46 * s, ry: 15 * s, fill: "#ffffff", opacity: 0.9 }, c);
      svgEl("ellipse", { cx: -28 * s, cy: 6 * s, rx: 30 * s, ry: 11 * s, fill: "#ffffff", opacity: 0.85 }, c);
      svgEl("ellipse", { cx: 30 * s, cy: 5 * s, rx: 32 * s, ry: 12 * s, fill: "#ffffff", opacity: 0.85 }, c);
      this.clouds.push(c);
    }

    // 远山（视差 0.35）
    const hillLayer = svgEl("g", { id: "hills" }, svg);
    for (let i = 0; i < 2; i++) {
      const h = svgEl("g", {}, hillLayer) as SVGGElement;
      // 周期性波形（首尾斜率一致），双份拼接处无接缝；第二层反相 + 下移制造层次
      svgEl(
        "path",
        {
          d:
            i === 0
              ? "M0 470 Q120 390 240 470 T480 470 T720 470 T960 470 L960 540 L0 540 Z"
              : "M0 470 Q120 550 240 470 T480 470 T720 470 T960 470 L960 540 L0 540 Z",
          fill: i === 0 ? "#cfe3c8" : "#c3dabb",
          transform: i === 1 ? "translate(0,10)" : undefined,
        },
        h,
      );
      this.hills.push(h);
    }

    // 地面
    svgEl("rect", { x: 0, y: GROUND_Y, width: VIEW_W, height: VIEW_H - GROUND_Y, fill: "#cbb78d" }, svg);
    svgEl("rect", { x: 0, y: GROUND_Y, width: VIEW_W, height: 10, fill: "#b3a077" }, svg);
    const stripeLayer = svgEl("g", { id: "stripes" }, svg);
    for (let i = 0; i < 9; i++) {
      const g = svgEl("g", {}, stripeLayer) as SVGGElement;
      svgEl("path", { d: "M0 0 l7 -14 l7 14 Z", fill: "#9db47f" }, g);
      svgEl("rect", { x: 18, y: -3, width: 26, height: 3, rx: 1.5, fill: "#b8a47c" }, g);
      this.stripes.push(g);
    }

    // 世界实体层（石头 / 掉落物）
    this.worldLayer = svgEl("g", { id: "world" }, svg) as SVGGElement;

    // 影子
    this.shadow = svgEl("ellipse", { cx: BIKE_SCREEN_X, cy: GROUND_Y + 6, rx: 110, ry: 8, fill: "#000", opacity: 0.16 }, svg) as SVGEllipseElement;

    // 自行车 + 鹈鹕
    this.bikeGroup = svgEl("g", { id: "bike" }, svg) as SVGGElement;
    this.buildBike();

    // HUD
    this.hudMode = svgEl("text", { x: 18, y: 30, "font-size": 17, "font-family": "monospace", fill: "#2f4858" }, svg) as SVGTextElement;
    this.hudInfo = svgEl("text", { x: 18, y: 52, "font-size": 13, "font-family": "monospace", fill: "#5a6b78" }, svg) as SVGTextElement;
  }

  private buildBike(): void {
    const b = this.bikeGroup;
    const r = this.refs;

    // ---- 远侧：腿 + 曲柄 + 踏板（颜色更深，位于车架后） ----
    const farLayer = svgEl("g", { id: "layer-far" }, b);
    r.legFar = svgEl("path", { stroke: LEG_FAR, "stroke-width": 8, fill: "none", "stroke-linecap": "round" }, farLayer);
    r.footFar = svgEl("path", { stroke: LEG_FAR, "stroke-width": 5, fill: "none", "stroke-linecap": "round" }, farLayer);
    r.crankArmFar = svgEl("line", { stroke: "#6d675f", "stroke-width": 5, "stroke-linecap": "round" }, farLayer);
    r.pedalFar = svgEl("rect", { x: -9, y: -2.5, width: 18, height: 5, rx: 2, fill: "#5d574f" }, farLayer);
    r.markerPedalFar = svgEl("circle", { id: "marker-pedal-far", r: 2, fill: "#2e7d32", opacity: 0.9 }, farLayer);
    r.markerFootFar = svgEl("circle", { id: "marker-foot-far", r: 2, fill: "#2e7d32", opacity: 0.9 }, farLayer);

    // ---- 远侧翅膀（搭在身上，轻微扇动） ----
    this.wingFar = svgEl("g", { id: "wing-far" }, b) as SVGGElement;
    svgEl("path", { d: `M ${GEO.shoulder.x - 4} ${GEO.shoulder.y + 2} Q ${GEO.shoulder.x - 26} ${GEO.shoulder.y + 14} ${GEO.shoulder.x - 40} ${GEO.shoulder.y + 30}`, stroke: BODY_SHADE, "stroke-width": 9, fill: "none", "stroke-linecap": "round" }, this.wingFar);

    // ---- 后轮 ----
    r.wheelRear = this.buildWheel(b, "wheel-rear", GEO.rearWheel);

    // ---- 车架 ----
    const frameG = svgEl("g", { id: "frame" }, b);
    const F = (x1: number, y1: number, x2: number, y2: number) =>
      svgEl("line", { x1, y1, x2, y2, stroke: FRAME, "stroke-width": 5, "stroke-linecap": "round" }, frameG);
    F(GEO.crank.x, GEO.crank.y, GEO.seat.x + 4, GEO.seat.y + 4); // 座管
    F(GEO.crank.x, GEO.crank.y, GEO.headTubeTop.x, GEO.headTubeTop.y); // 下管
    F(GEO.seat.x + 4, GEO.seat.y + 4, GEO.headTubeTop.x, GEO.headTubeTop.y); // 上管
    F(GEO.crank.x, GEO.crank.y, GEO.rearWheel.x, GEO.rearWheel.y); // 后下叉
    F(GEO.seat.x + 4, GEO.seat.y + 4, GEO.rearWheel.x, GEO.rearWheel.y); // 后上叉
    F(GEO.headTubeTop.x, GEO.headTubeTop.y, GEO.frontWheel.x, GEO.frontWheel.y); // 前叉
    F(GEO.headTubeTop.x, GEO.headTubeTop.y, GEO.grip.x, GEO.grip.y); // 把立
    svgEl("line", { x1: GEO.grip.x - 10, y1: GEO.grip.y - 2, x2: GEO.grip.x + 8, y2: GEO.grip.y + 2, stroke: INK, "stroke-width": 5, "stroke-linecap": "round" }, frameG); // 车把横杆
    // 传动：牙盘 / 飞轮 / 链条
    svgEl("line", { x1: GEO.crank.x, y1: GEO.crank.y - 13, x2: GEO.rearWheel.x, y2: GEO.rearWheel.y - 6, stroke: "#57534b", "stroke-width": 2 }, frameG);
    svgEl("line", { x1: GEO.crank.x, y1: GEO.crank.y + 13, x2: GEO.rearWheel.x, y2: GEO.rearWheel.y + 6, stroke: "#57534b", "stroke-width": 2 }, frameG);
    svgEl("circle", { cx: GEO.crank.x, cy: GEO.crank.y, r: 13, fill: "none", stroke: "#57534b", "stroke-width": 3 }, frameG);
    svgEl("circle", { cx: GEO.rearWheel.x, cy: GEO.rearWheel.y, r: 6, fill: "#57534b" }, frameG);
    // 座垫
    svgEl("line", { x1: GEO.seat.x - 12, y1: GEO.seat.y - 2, x2: GEO.seat.x + 12, y2: GEO.seat.y - 2, stroke: INK, "stroke-width": 7, "stroke-linecap": "round" }, frameG);
    // 握把标记点
    r.markerGrip = svgEl("circle", { id: "marker-grip", cx: GEO.grip.x, cy: GEO.grip.y, r: 2.4, fill: "#c62828", opacity: 0.9 }, frameG);

    // ---- 前轮 ----
    r.wheelFront = this.buildWheel(b, "wheel-front", GEO.frontWheel);

    // ---- 鹈鹕上身（身体 / 尾羽 / 颈 / 头，绕髋部后仰） ----
    this.upperGroup = svgEl("g", { id: "pelican-upper" }, b) as SVGGElement;
    const u = this.upperGroup;
    svgEl("path", { d: `M ${GEO.hip.x - 6} ${GEO.hip.y - 30} L ${GEO.hip.x - 40} ${GEO.hip.y - 40} L ${GEO.hip.x - 36} ${GEO.hip.y - 22} L ${GEO.hip.x - 6} ${GEO.hip.y - 14} Z`, fill: BODY_SHADE, stroke: INK, "stroke-width": 1.5 }, u); // 尾羽
    svgEl("ellipse", { cx: -8, cy: -152, rx: 34, ry: 25, fill: BODY_FILL, stroke: INK, "stroke-width": 2, transform: "rotate(-10 -8 -152)" }, u); // 身体
    svgEl("path", { d: "M 8 -166 Q 16 -190 32 -204", stroke: BODY_FILL, "stroke-width": 15, fill: "none", "stroke-linecap": "round" }, u); // 颈
    svgEl("path", { d: "M 8 -166 Q 16 -190 32 -204", stroke: INK, "stroke-width": 2, fill: "none", opacity: 0.35, transform: "translate(0,7)" }, u);

    // 头组（抬头动作）
    this.headGroup = svgEl("g", { id: "head" }, u) as SVGGElement;
    const hd = this.headGroup;
    this.pouch = svgEl("path", { d: "M 42 -201 Q 74 -172 106 -194 Q 76 -188 42 -201 Z", fill: POUCH, stroke: "#d18f2f", "stroke-width": 1.5 }, hd) as SVGPathElement; // 喉囊
    svgEl("path", { d: `M 40 ${GEO.head.y - 8} L ${GEO.beakTip.x} ${GEO.beakTip.y - 4} L ${GEO.beakTip.x - 2} ${GEO.beakTip.y + 2} L 42 ${GEO.head.y + 2} Z`, fill: BEAK, stroke: "#c77f28", "stroke-width": 1.5 }, hd); // 长喙上颚
    svgEl("circle", { cx: GEO.head.x, cy: GEO.head.y, r: 11.5, fill: BODY_FILL, stroke: INK, "stroke-width": 2 }, hd); // 头
    svgEl("circle", { cx: 37, cy: -211, r: 2.4, fill: INK }, hd); // 眼
    svgEl("circle", { cx: 37.8, cy: -211.8, r: 0.8, fill: "#fff" }, hd);
    svgEl("path", { d: "M 28 -218 L 22 -228 M 33 -219 L 30 -230", stroke: BODY_SHADE, "stroke-width": 2.5, "stroke-linecap": "round" }, hd); // 冠羽

    // ---- 近侧：曲柄 + 踏板 + 腿 + 脚 ----
    const nearLayer = svgEl("g", { id: "layer-near" }, b);
    r.crankArmNear = svgEl("line", { stroke: "#4c4740", "stroke-width": 5.5, "stroke-linecap": "round" }, nearLayer);
    r.pedalNear = svgEl("rect", { x: -9, y: -2.5, width: 18, height: 5, rx: 2, fill: "#3f3a33" }, nearLayer);
    r.legNear = svgEl("path", { stroke: LEG, "stroke-width": 9, fill: "none", "stroke-linecap": "round" }, nearLayer);
    r.kneeNear = svgEl("circle", { r: 4.5, fill: LEG, stroke: "#b57d28", "stroke-width": 1 }, nearLayer);
    r.footNear = svgEl("path", { stroke: "#d98f2c", "stroke-width": 5.5, fill: "none", "stroke-linecap": "round" }, nearLayer);
    r.markerPedalNear = svgEl("circle", { id: "marker-pedal-near", r: 2, fill: "#2e7d32" }, nearLayer);
    r.markerFootNear = svgEl("circle", { id: "marker-foot-near", r: 2, fill: "#2e7d32" }, nearLayer);
    svgEl("circle", { cx: GEO.crank.x, cy: GEO.crank.y, r: 3.2, fill: "#3f3a33" }, nearLayer);

    // ---- 近侧翅膀：肩 → 肘 → 车把（翅尖始终接触握把） ----
    r.wingUpper = svgEl("line", { stroke: BODY_FILL, "stroke-width": 12, "stroke-linecap": "round" }, b);
    r.wingUpperInk = svgEl("line", { stroke: INK, "stroke-width": 2, opacity: 0.3, "stroke-linecap": "round" }, b);
    r.wingFore = svgEl("line", { stroke: BODY_FILL, "stroke-width": 9, "stroke-linecap": "round" }, b);
    r.wingTipDot = svgEl("circle", { r: 4.2, fill: BODY_SHADE, stroke: INK, "stroke-width": 1.5 }, b); // 翅尖（手状钩）
    r.markerWingTip = svgEl("circle", { id: "marker-wing-tip", r: 2.4, fill: "#c62828", opacity: 0.9 }, b);
  }

  private buildWheel(parent: SVGGElement, id: string, c: Pt): SVGGElement {
    const g = svgEl("g", { id, transform: `translate(${c.x},${c.y})` }, parent) as SVGGElement;
    const spin = svgEl("g", { class: "spin" }, g) as SVGGElement;
    if (id === "wheel-rear") this.spinRear = spin;
    else if (id === "wheel-front") this.spinFront = spin;
    for (let i = 0; i < 8; i++) {
      const a = (i * Math.PI) / 4;
      svgEl("line", { x1: -Math.cos(a) * 34, y1: -Math.sin(a) * 34, x2: Math.cos(a) * 34, y2: Math.sin(a) * 34, stroke: "#8d8d8d", "stroke-width": 1.6 }, spin);
    }
    svgEl("circle", { r: WHEEL_R, fill: "none", stroke: TIRE, "stroke-width": 7 }, g);
    svgEl("circle", { r: 34.5, fill: "none", stroke: "#a9a9a9", "stroke-width": 2 }, g);
    svgEl("circle", { r: 4.5, fill: "#6d6d6d" }, g);
    svgEl("circle", { r: 1.8, cx: 30, cy: 0, fill: "#e0e0e0", opacity: 0.85 }, spin); // 辐条反光点，便于观察旋转
    return g;
  }

  private stoneNode(id: string, s: { w: number; h: number }): SVGGElement {
    const g = svgEl("g", { id: `ent-${id}` }, this.worldLayer) as SVGGElement;
    const w = s.w;
    const h = s.h;
    svgEl(
      "path",
      {
        d: `M ${-w / 2} 0 L ${-w / 2 + 5} ${-h * 0.65} L ${-w * 0.12} ${-h} L ${w / 2 - 7} ${-h * 0.8} L ${w / 2} 0 Z`,
        fill: "#8b8578",
        stroke: "#5f5a4f",
        "stroke-width": 2,
      },
      g,
    );
    svgEl("path", { d: `M ${-w * 0.12} ${-h} L ${-w * 0.05} ${-h * 0.45} L ${w * 0.18} ${-h * 0.5}`, stroke: "#6f6a5e", "stroke-width": 1.6, fill: "none" }, g);
    return g;
  }

  private dropNode(id: string, r: number): SVGGElement {
    const g = svgEl("g", { id: `ent-${id}` }, this.worldLayer) as SVGGElement;
    svgEl("path", { d: `M ${-r} 2 L ${-r * 0.55} ${-r * 0.8} L ${r * 0.15} ${-r} L ${r} ${-r * 0.2} L ${r * 0.6} ${r * 0.8} L ${-r * 0.3} ${r} Z`, fill: "#7a6a5d", stroke: "#4e4238", "stroke-width": 2 }, g);
    svgEl("path", { d: `M ${-r * 0.4} ${-r * 0.4} L ${r * 0.1} ${-r * 0.1} L ${r * 0.35} ${r * 0.35}`, stroke: "#5d5147", "stroke-width": 1.5, fill: "none" }, g);
    const trail = svgEl("g", { class: "trail" }, g) as SVGGElement;
    svgEl("line", { x1: -3, y1: -r - 6, x2: -3, y2: -r - 20, stroke: "#8a7d70", "stroke-width": 2, opacity: 0.7 }, trail);
    svgEl("line", { x1: 4, y1: -r - 10, x2: 4, y2: -r - 26, stroke: "#8a7d70", "stroke-width": 2, opacity: 0.5 }, trail);
    const dust = svgEl("g", { class: "dust", opacity: 0 }, g) as SVGGElement;
    svgEl("circle", { cx: -r - 4, cy: r * 0.6, r: 4, fill: "#c9b993" }, dust);
    svgEl("circle", { cx: r + 5, cy: r * 0.6, r: 5, fill: "#c9b993" }, dust);
    this.trailNodes.set(id, trail);
    this.dustNodes.set(id, dust);
    return g;
  }

  update(sim: Simulation): void {
    const r = this.refs;
    const bikeX = sim.bikeX;

    // 视差背景
    const cm = (v: number, m: number) => ((v % m) + m) % m;
    const cloudBases = [140, 520, 830];
    this.clouds.forEach((c, i) => {
      const x = cm(cloudBases[i] - bikeX * 0.15, 1300) - 170;
      setA(c, "transform", `translate(${x.toFixed(1)},${70 + i * 46})`);
    });
    const hillX = -cm(bikeX * 0.3, 960);
    setA(this.hills[0], "transform", `translate(${hillX.toFixed(1)},0)`);
    setA(this.hills[1], "transform", `translate(${(hillX + 960).toFixed(1)},0)`);
    this.stripes.forEach((g, i) => {
      const x = cm(i * 160 + 40 - bikeX, 1440) - 240;
      setA(g, "transform", `translate(${x.toFixed(1)},${GROUND_Y + 26 + (i % 3) * 22})`);
      setA(g, "opacity", x > -60 && x < VIEW_W + 60 ? 1 : 0);
    });

    // 车组整体（跃起时抬升）
    setA(this.bikeGroup, "transform", `translate(${BIKE_SCREEN_X},${GROUND_Y - sim.lift})`);
    setA(this.shadow, "rx", 110 - sim.lift * 0.6);
    setA(this.shadow, "opacity", 0.16 - sim.lift * 0.0016);

    // 车轮 / 曲柄同步旋转（spin 节点在 buildWheel 时已缓存，不再逐帧 querySelector）
    const wheelDeg = (sim.wheelAngle * 180) / Math.PI;
    setA(this.spinRear, "transform", `rotate(${wheelDeg.toFixed(2)})`);
    setA(this.spinFront, "transform", `rotate(${wheelDeg.toFixed(2)})`);

    // 踏板 / 曲柄 / 腿（脚与踏板刚性绑定：IK 目标即踏板点）
    const pN = sim.pedalPos(0);
    const pF = sim.pedalPos(Math.PI);
    const legN = sim.legIK(GEO.hip, pN, -1);
    const legF = sim.legIK(GEO.hipFar, pF, -1);

    setA(r.crankArmNear, "x1", GEO.crank.x);
    setA(r.crankArmNear, "y1", GEO.crank.y);
    setA(r.crankArmNear, "x2", pN.x);
    setA(r.crankArmNear, "y2", pN.y);
    setA(r.crankArmFar, "x1", GEO.crank.x);
    setA(r.crankArmFar, "y1", GEO.crank.y);
    setA(r.crankArmFar, "x2", pF.x);
    setA(r.crankArmFar, "y2", pF.y);
    setA(r.pedalNear, "transform", `translate(${pN.x},${pN.y})`);
    setA(r.pedalFar, "transform", `translate(${pF.x},${pF.y})`);

    setA(r.legNear, "d", `M ${GEO.hip.x} ${GEO.hip.y} L ${legN.joint.x.toFixed(2)} ${legN.joint.y.toFixed(2)} L ${legN.target.x.toFixed(2)} ${legN.target.y.toFixed(2)}`);
    setA(r.kneeNear, "cx", legN.joint.x.toFixed(2));
    setA(r.kneeNear, "cy", legN.joint.y.toFixed(2));
    setA(r.footNear, "d", `M ${legN.target.x.toFixed(2)} ${legN.target.y.toFixed(2)} l 15 1`);
    setA(r.legFar, "d", `M ${GEO.hipFar.x} ${GEO.hipFar.y} L ${legF.joint.x.toFixed(2)} ${legF.joint.y.toFixed(2)} L ${legF.target.x.toFixed(2)} ${legF.target.y.toFixed(2)}`);
    setA(r.footFar, "d", `M ${legF.target.x.toFixed(2)} ${legF.target.y.toFixed(2)} l 15 1`);

    setA(r.markerPedalNear, "cx", pN.x);
    setA(r.markerPedalNear, "cy", pN.y);
    setA(r.markerFootNear, "cx", legN.target.x);
    setA(r.markerFootNear, "cy", legN.target.y);
    setA(r.markerPedalFar, "cx", pF.x);
    setA(r.markerPedalFar, "cy", pF.y);
    setA(r.markerFootFar, "cx", legF.target.x);
    setA(r.markerFootFar, "cy", legF.target.y);

    // 上身后仰（髋部为轴）
    setA(this.upperGroup, "transform", `rotate(${((sim.lean * 180) / Math.PI).toFixed(2)} ${GEO.hip.x} ${GEO.hip.y})`);
    // 抬头看坠落物（颈根为轴）
    setA(this.headGroup, "transform", `rotate(${((-0.32 * sim.headAim * 180) / Math.PI).toFixed(2)} ${GEO.neckBase.x} ${GEO.neckBase.y})`);
    // 喉囊轻微摆动
    const sag = -172 + Math.sin(sim.t * 2.4) * 3 - sim.headAim * 6;
    setA(this.pouch, "d", `M 42 -201 Q 74 ${sag.toFixed(1)} 106 -194 Q 76 ${(-188 - sim.headAim * 4).toFixed(1)} 42 -201 Z`);
    // 远侧翅膀轻微扇动（近侧翅膀必须扶把，不扇动）
    setA(this.wingFar, "transform", `rotate(${(Math.sin(sim.t * 3.2) * 4).toFixed(2)} ${GEO.shoulder.x} ${GEO.shoulder.y})`);

    // 近侧翅膀：肩（随后仰）→ 肘 → 握把（IK，翅尖精确落在握把上）
    const sh = sim.shoulderPos();
    const wing = sim.wingIK();
    const seg = (el: SVGElement | undefined, x1: number, y1: number, x2: number, y2: number) => {
      if (!el) return;
      setA(el, "x1", x1.toFixed(2));
      setA(el, "y1", y1.toFixed(2));
      setA(el, "x2", x2.toFixed(2));
      setA(el, "y2", y2.toFixed(2));
    };
    seg(r.wingUpper, sh.x, sh.y, wing.joint.x, wing.joint.y);
    seg(r.wingUpperInk, sh.x, sh.y + 4, wing.joint.x, wing.joint.y + 3);
    seg(r.wingFore, wing.joint.x, wing.joint.y, GEO.grip.x, GEO.grip.y);
    setA(r.wingTipDot, "cx", GEO.grip.x);
    setA(r.wingTipDot, "cy", GEO.grip.y);
    setA(r.markerWingTip, "cx", GEO.grip.x);
    setA(r.markerWingTip, "cy", GEO.grip.y);

    // 世界实体
    const screenX = (wx: number) => wx - bikeX + BIKE_SCREEN_X;
    const aliveStones = new Set<string>();
    for (const s of sim.stones()) {
      aliveStones.add(s.id);
      let g = this.stoneNodes.get(s.id);
      if (!g) {
        g = this.stoneNode(s.id, s);
        this.stoneNodes.set(s.id, g);
      }
      const sx = screenX(s.x);
      setA(g, "transform", `translate(${sx.toFixed(1)},${GROUND_Y})`);
      setA(g, "display", sx > -120 && sx < VIEW_W + 120 ? "" : "none");
    }
    const aliveDrops = new Set<string>();
    for (const d of sim.drops()) {
      aliveDrops.add(d.id);
      let g = this.dropNodes.get(d.id);
      if (!g) {
        g = this.dropNode(d.id, d.r);
        this.dropNodes.set(d.id, g);
      }
      const sx = screenX(d.x);
      const sy = GROUND_Y - d.alt;
      setA(g, "transform", `translate(${sx.toFixed(1)},${sy.toFixed(1)})`);
      const visible = !d.gone && sx > -120 && sx < VIEW_W + 120;
      setA(g, "display", visible ? "" : "none");
      setA(this.trailNodes.get(d.id), "opacity", !d.landed ? 1 : 0);
      const dust = this.dustNodes.get(d.id);
      if (dust) {
        const k = d.landed && !d.gone ? Math.max(0, 1 - (sim.t - d.landTime) / DROP_GONE_DELAY) : 0;
        setA(dust, "opacity", k.toFixed(2));
        setA(dust, "transform", `scale(${(1 + (1 - k) * 0.8).toFixed(2)})`);
      }
    }
    for (const [id, g] of this.stoneNodes) {
      if (!aliveStones.has(id)) {
        g.remove();
        this.stoneNodes.delete(id);
      }
    }
    for (const [id, g] of this.dropNodes) {
      if (!aliveDrops.has(id)) {
        g.remove();
        this.dropNodes.delete(id);
        this.trailNodes.delete(id);
        this.dustNodes.delete(id);
      }
    }

    // HUD
    this.hudMode.textContent = `状态 ${MODE_ZH[sim.mode]}  速度 ${sim.v.toFixed(0)} px/s  时间 ${sim.t.toFixed(2)}s`;
    const info: string[] = [];
    for (const s of sim.threatStones().slice(0, 1)) info.push(`石头 ${s.id} 距前轮 ${(s.x - sim.frontX).toFixed(0)}px`);
    for (const d of sim.threatDrops().slice(0, 1)) info.push(`坠落物 ${d.id} 高度 ${d.alt.toFixed(0)}px${d.landed ? " 已落地" : ""}`);
    this.hudInfo.textContent = info.join("  |  ");
  }
}
