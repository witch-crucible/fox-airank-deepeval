export function createGameState(options = {}) {
  const width = options.width ?? 480, height = options.height ?? 640;
  return { width, height, player: { x: (width - 40) / 2, y: height - 68, w: 40, h: 48, lives: 3 }, bullets: [], enemies: [], score: 0, status: "playing", cooldown: 0, spawnTimer: 0.8, rng: options.random ?? Math.random };
}
export function movePlayer(state, dx) { if (state.status === "playing") state.player.x = Math.max(0, Math.min(state.width - state.player.w, state.player.x + dx)); }
export function shoot(state) {
  if (state.status !== "playing" || state.cooldown > 0) return;
  state.bullets.push({ x: state.player.x + state.player.w / 2 - 2, y: state.player.y, w: 4, h: 12, speed: 320 }); state.cooldown = 0.3;
}
const overlap = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
export function update(state, dt) {
  if (dt <= 0 || state.status !== "playing") return;
  state.cooldown = Math.max(0, state.cooldown - dt);
  for (let i = state.bullets.length - 1; i >= 0; i--) { const b = state.bullets[i]; b.y -= b.speed * dt; if (b.y + b.h <= 0) state.bullets.splice(i, 1); }
  state.spawnTimer -= dt;
  while (state.spawnTimer <= 0) { state.enemies.push({ x: state.rng() * (state.width - 32), y: -32, w: 32, h: 32, speed: 90 + state.rng() * 80, score: 10 }); state.spawnTimer += 0.8; }
  for (let i = state.enemies.length - 1; i >= 0; i--) { const e = state.enemies[i]; e.y += e.speed * dt; if (e.y > state.height) state.enemies.splice(i, 1); }
  const hit = new Set();
  for (let i = state.bullets.length - 1; i >= 0; i--) for (const e of state.enemies) if (!hit.has(e) && overlap(state.bullets[i], e)) { hit.add(e); state.score += e.score; state.bullets.splice(i, 1); break; }
  for (let i = state.enemies.length - 1; i >= 0; i--) { const e = state.enemies[i]; if (hit.has(e) || overlap(e, state.player)) { state.enemies.splice(i, 1); if (!hit.has(e)) state.player.lives--; } }
  if (state.player.lives <= 0) state.status = "gameover";
}
export function restart(state) { const fresh = createGameState(state); Object.assign(state, fresh); }
