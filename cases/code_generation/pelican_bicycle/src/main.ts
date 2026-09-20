// ===== 启动入口：rAF 播放循环 + 供自动化验证使用的确定性 API =====

(function boot() {
  const svg = document.getElementById("stage") as unknown as SVGSVGElement;
  const sim = new Simulation();
  const renderer = new Renderer(svg, sim);

  let playing = true;
  let acc = 0;
  let last = performance.now();

  function frame(now: number): void {
    const elapsed = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (playing) {
      acc += elapsed;
      let guard = 0;
      while (acc >= DT && guard < 240) {
        sim.step(DT);
        acc -= DT;
        guard += 1;
      }
      renderer.update(sim);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  const api = {
    version: 1,
    constants: {
      DT,
      VIEW_W,
      VIEW_H,
      GROUND_Y,
      BIKE_SCREEN_X,
      WHEEL_R,
      FRONT_OFFSET,
      CRUISE_SPEED,
      APPROACH_MIN,
      HOP_H,
      HOP_LEN,
      SAFE_GAP,
      CYCLE_T,
      GEO,
    },
    sim,
    renderer,
    play(): void {
      if (!playing) {
        playing = true;
        last = performance.now();
        acc = 0;
      }
    },
    pause(): void {
      playing = false;
    },
    reset(): void {
      sim.reset();
      renderer.update(sim);
    },
    // 确定性跳转：从 0 以固定步长推进到 t（暂停播放）
    seek(t: number): void {
      playing = false;
      sim.reset();
      const n = Math.round(t / DT);
      for (let i = 0; i < n; i++) sim.step(DT);
      renderer.update(sim);
    },
    stepOnce(dt: number = DT): void {
      playing = false;
      sim.step(dt);
      renderer.update(sim);
    },
    snapshot(): ReturnType<Simulation["snapshot"]> {
      return sim.snapshot();
    },
    geometry(): ReturnType<Simulation["geometry"]> {
      return sim.geometry();
    },
  };

  (window as unknown as { pelican: typeof api }).pelican = api;
  document.body.dataset.ready = "yes";
})();
