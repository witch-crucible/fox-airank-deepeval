# 生成像素风打飞机小游戏

实现一个浏览器可直接游玩的像素风竖版打飞机小游戏：玩家飞机位于屏幕底部，敌机从顶部生成并下落，子弹击中敌机得分，敌机撞到玩家扣命，生命归零游戏结束。**禁止使用第三方库**，纯原生 HTML/CSS/JavaScript（ES module）。

## 玩法说明

- 玩家飞机位于屏幕底部，键盘 `←`/`→` 移动，`空格` 射击，`R` 重新开始。
- 敌机从顶部随机横向位置生成并向下移动；子弹击中敌机得分（每架 10 分）。
- 敌机撞到玩家扣 1 条命；生命归零时游戏结束。
- 渲染为像素风 Canvas：星空/视差背景、方块像素绘制；HUD 显示分数与生命；游戏结束时显示 game over 画面。
- 通过本地静态服务器打开 `index.html` 游玩（ES module 加载限制，不能用 file:// 直接打开）。

## 架构要求

`game-logic.js` 必须是**与 DOM 无关的纯逻辑 ES 模块**，可在 Node 中直接 import（评分器会无头调用）。`game.js` 为渲染层，**必须 `import` 并使用 `game-logic.js` 导出的函数**；`index.html` 通过 `<script type="module" src="game.js">` 接入。

`game-logic.js` 导出以下函数：

```
createGameState(options) -> state
movePlayer(state, dx)
shoot(state)
update(state, dt)
restart(state)
```

## API 契约

### createGameState(options)

`options: { width = 480, height = 640, random = Math.random }`。返回 state：

```js
{
  width, height,
  player: { x: (width - 40) / 2, y: height - 48 - 20, w: 40, h: 48, lives: 3 },
  bullets: [],   // 每发 { x, y, w: 4, h: 12, speed: 320 }
  enemies: [],   // 每架 { x, y, w: 32, h: 32, speed, score: 10 }
  score: 0,
  status: "playing",
  cooldown: 0,
  spawnTimer: 0.8,
  rng: random
}
```

`spawnTimer` 初始为 `0.8`（首个敌机在开赛后约 0.8 秒出现），后续每 0.8 秒生成一架。

### movePlayer(state, dx)

仅 `status === "playing"` 时生效；`state.player.x` 限制在 `[0, width - player.w]`。

### shoot(state)

仅 `status === "playing"` 且 `cooldown <= 0` 时生成一发子弹 `{ x: player.x + player.w/2 - 2, y: player.y, w: 4, h: 12, speed: 320 }`，并置 `cooldown = 0.3`。

### update(state, dt)

`dt <= 0` 或 `status !== "playing"` 时直接返回。否则按顺序执行：

1. `cooldown = max(0, cooldown - dt)`。
2. 子弹上移：每发 `y -= speed * dt`；`y + h <= 0` 的移除。
3. 敌机生成：`spawnTimer -= dt`；while `spawnTimer <= 0`：生成一架 `{ x: rng() * (width - 32), y: -32, w: 32, h: 32, speed: 90 + rng() * 80, score: 10 }`，`spawnTimer += 0.8`。
4. 敌机下移：每架 `y += speed * dt`；`y > height` 的移除。
5. AABB 碰撞（`a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y`）：
   - 子弹-敌机：每发子弹命中一架敌机（每架只记一次）→ 敌机移除、`score += enemy.score`、子弹移除。
   - 敌机-玩家：命中则敌机移除、`player.lives -= 1`；`lives <= 0` 时 `status = "gameover"`。

### restart(state)

原地重置为初始状态（保留 `width`/`height`/`rng`）：`lives = 3`、`score = 0`、`bullets = []`、`enemies = []`、`status = "playing"`、`cooldown = 0`、`spawnTimer = 0.8`。

## 渲染要求

- `game.js` 渲染层 import `game-logic.js` 并调用其函数驱动玩法。
- Canvas 像素风：星空/视差背景、玩家/敌机/子弹以方块像素绘制。
- HUD 显示当前分数与剩余生命。
- 生命归零时显示 game over 画面，可按 `R` 重新开始。

## 验证要求

1. 执行 `npm test`（运行 `public-test.mjs`），必须全部通过。
2. 通过 `python3 -m http.server` 打开 `index.html` 游玩，确认画面与操作正常。
3. 按 `RESULT_PROTOCOL.md` 生成 `result.json`。

**禁止使用第三方库**（不得安装或引用任何 npm 依赖、框架或 CDN 资源）。