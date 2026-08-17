export function createGameState(options = {}) {
  const width = options.width ?? 480;
  const height = options.height ?? 640;
  const random = options.random ?? Math.random;
  return {
    width,
    height,
    player: { x: (width - 40) / 2, y: height - 48 - 20, w: 40, h: 48, lives: 3 },
    bullets: [],
    enemies: [],
    score: 0,
    status: "playing",
    cooldown: 0,
    spawnTimer: 0.8,
    rng: random,
  };
}

export function movePlayer(state, dx) {
  if (state.status !== "playing") return;
  state.player.x = Math.max(0, Math.min(state.width - state.player.w, state.player.x + dx));
}

export function shoot(state) {
  if (state.status !== "playing" || state.cooldown > 0) return;
  const { player } = state;
  state.bullets.push({ x: player.x + player.w / 2 - 2, y: player.y, w: 4, h: 12, speed: 320 });
  state.cooldown = 0.3;
}

export function update(state, dt) {
  if (dt <= 0 || state.status !== "playing") return;

  state.cooldown = Math.max(0, state.cooldown - dt);

  for (let i = state.bullets.length - 1; i >= 0; i -= 1) {
    const bullet = state.bullets[i];
    bullet.y -= bullet.speed * dt;
    if (bullet.y + bullet.h <= 0) state.bullets.splice(i, 1);
  }

  state.spawnTimer -= dt;
  while (state.spawnTimer <= 0) {
    state.enemies.push({
      x: state.rng() * (state.width - 32),
      y: -32,
      w: 32,
      h: 32,
      speed: 90 + state.rng() * 80,
      score: 10,
    });
    state.spawnTimer += 0.8;
  }

  for (let i = state.enemies.length - 1; i >= 0; i -= 1) {
    const enemy = state.enemies[i];
    enemy.y += enemy.speed * dt;
    if (enemy.y > state.height) state.enemies.splice(i, 1);
  }

  const hitEnemies = new Set();
  for (let i = state.bullets.length - 1; i >= 0; i -= 1) {
    const bullet = state.bullets[i];
    for (const enemy of state.enemies) {
      if (
        !hitEnemies.has(enemy) &&
        bullet.x < enemy.x + enemy.w &&
        bullet.x + bullet.w > enemy.x &&
        bullet.y < enemy.y + enemy.h &&
        bullet.y + bullet.h > enemy.y
      ) {
        hitEnemies.add(enemy);
        state.score += enemy.score;
        state.bullets.splice(i, 1);
        break;
      }
    }
  }

  for (let i = state.enemies.length - 1; i >= 0; i -= 1) {
    const enemy = state.enemies[i];
    if (hitEnemies.has(enemy)) {
      state.enemies.splice(i, 1);
      continue;
    }
    const { player } = state;
    if (
      enemy.x < player.x + player.w &&
      enemy.x + enemy.w > player.x &&
      enemy.y < player.y + player.h &&
      enemy.y + enemy.h > player.y
    ) {
      state.enemies.splice(i, 1);
      player.lives -= 1;
      if (player.lives <= 0) state.status = "gameover";
    }
  }
}

export function restart(state) {
  state.player.x = (state.width - 40) / 2;
  state.player.y = state.height - 48 - 20;
  state.player.lives = 3;
  state.bullets = [];
  state.enemies = [];
  state.score = 0;
  state.status = "playing";
  state.cooldown = 0;
  state.spawnTimer = 0.8;
}