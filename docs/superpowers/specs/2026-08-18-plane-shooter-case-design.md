# write-plane-shooter Case 设计：像素风打飞机小游戏

日期：2026-08-18
状态：已批准（用户已确认：纯逻辑自动评分；玩法要素为移动与射击、敌机生成与计分、碰撞与生命）

## 背景与目标

在 `cases/code_generation/` 下新增第 4 个代码生成 case。任务要求代码代理生成一个**像素风打飞机小游戏**，浏览器可直接游玩，且核心玩法逻辑可在 Node 中无头自动评分。

参考同类游戏：雷电、小蜜蜂（竖版射击）。本 case 不要求 2.5D 等距渲染（原需求已由用户改为打飞机题材）。

## 评分方式

沿用现有 `"type": "javascript"` 隐藏检查机制，不扩展评分器：

- 隐藏检查位于 `benchmark/specs.json`，每个 check 是一段 Node assert 代码，注入到 import 目标文件的 harness 中执行（cwd 为 case 工作区）。
- 功能 90 分 + 结果协议 10 分。
- 为保持确定性，`createGameState` 接受注入的 `random` 函数（默认 `Math.random`），隐藏检查传入固定随机序列。
- 渲染层（`game.js` / `index.html`）通过 fs 检查做弱验证（存在性 + 接线），不打开浏览器。

## Case 定义

- 目录：`cases/code_generation/plane_shooter/`（snake_case）
- `case.json`：`{"id":"write-plane-shooter","category":"code_generation","title":"生成像素风打飞机小游戏"}`
- `package.json`：`{"type":"module","scripts":{"test":"node public-test.mjs"}}`

### 玩法（TASK.md 要求）

- 玩家飞机位于屏幕底部，键盘 `←`/`→` 移动，`空格` 射击，`R` 重新开始。
- 敌机从顶部生成并下落；子弹击中敌机得分（每架 10 分）；敌机撞到玩家扣 1 条命；生命归零游戏结束。
- 渲染为像素风 Canvas（星空/视差背景、方块像素绘制），HUD 显示分数与生命。
- 通过本地静态服务器打开 `index.html` 游玩（ES module 加载限制，不能用 file:// 直接打开）。

### 架构要求（评分关键）

`game-logic.js` 必须是与 DOM 无关的纯逻辑 ES 模块，可在 Node 中直接 import：

```
createGameState(options) -> state
movePlayer(state, dx)
shoot(state)
update(state, dt)
restart(state)
```

state 结构（TASK.md 必须写明，隐藏检查直接操作这些字段）：

```js
{
  width, height,                 // 画布尺寸，默认 480x640
  player: { x, y, w: 40, h: 48, lives: 3 },
  bullets: [],                   // { x, y, w: 4, h: 12, speed: 320 }
  enemies: [],                   // { x, y, w: 32, h: 32, speed, score: 10 }
  score: 0,
  status: "playing" | "gameover",
  cooldown: 0,                   // 射击冷却，0.3s
  spawnTimer: 0.8,               // 敌机生成计时，初始 0.8s，之后每 0.8s 生成一架
  rng: random                    // 注入的随机函数
}
```

行为规则：

- `createGameState({width, height, random})`：`player.x = (width - 40) / 2`，`player.y = height - 48 - 20`。
- `movePlayer`：仅 `status === "playing"` 生效；`x` 限制在 `[0, width - 40]`。
- `shoot`：仅 `status === "playing"` 且 `cooldown <= 0` 时生成一发子弹（机头中心，`x = player.x + player.w/2 - 2, y = player.y`），并设置 `cooldown = 0.3`。
- `update(state, dt)`：`dt <= 0` 或非 playing 直接返回。
  - `cooldown = max(0, cooldown - dt)`。
  - 子弹上移 `y -= speed * dt`；完全出界（`y + h <= 0`）移除。
  - 敌机生成：`spawnTimer -= dt`，`<= 0` 时生成一架并 `spawnTimer += 0.8`（while 循环处理大 dt）；敌机 `{x: rng() * (width - 32), y: -32, speed: 90 + rng() * 80, score: 10}`。
  - 敌机下移 `y += speed * dt`；`y > height` 移除（飞出底部不扣命）。
  - AABB 碰撞（`a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y`）：
    - 子弹-敌机：敌机移除、`score += enemy.score`、子弹移除。
    - 敌机-玩家：敌机移除、`player.lives -= 1`；`lives <= 0` 时 `status = "gameover"`。
  - 执行顺序固定为：cooldown → 子弹移动 → 敌机生成 → 敌机移动 → 碰撞（契约与参考解一致）。
- `restart(state)`：原地重置为初始状态（保留 width/height/rng），`lives = 3, score = 0, bullets = [], enemies = [], status = "playing"`。

## 隐藏检查（benchmark/specs.json）

`file: "game-logic.js"`，共 6 条：

1. **移动边界**：`createGameState({width:400,height:600,random:()=>0.5})` → `player.x === 180`；`movePlayer(-999)` → `0`；`movePlayer(999)` → `360`。
2. **射击与冷却**：`shoot` 后 bullets 1 发；冷却未到再 `shoot` 仍 1 发；`update(s, 0.3)` 后可再射；`update(s, 0.016)` 后子弹 `y` 变小。
3. **敌机生成与移动**：注入 `random: () => 0.5`；`update(s, 2.0)` 后 `enemies.length >= 2` 且 `x` 在 `[0, width - w]`；记录首架 `y`，`update(s, 0.1)` 后仍在场且 `y` 变大。
4. **子弹命中计分**：手动 push 一架敌机与一发重叠子弹，`update(s, 0.016)` → 敌机与子弹均移除、`score === 10`。
5. **碰撞扣命与重开**：连续 3 次 push 敌机到玩家位置并 `update(s, 0.016)` → `lives === 0`、`status === "gameover"`、`score` 不因撞机增加；`restart` 后 `lives === 3`、`score === 0`、实体清空、`status === "playing"`。
6. **文件接线（fs）**：`index.html` 存在且含 `<canvas` 与 `<script`；`game.js` 存在且引用 `game-logic.js`。

检查 4/5 直接向 state 内部 push 对象（`speed: 0`），依赖 TASK.md 写明的字段结构。

## 可见测试（public-test.mjs）

覆盖：初始状态、移动边界、射击、一次子弹命中得分。`npm test` 通过。

## 参考解（tests/reference/）

- `game-logic.js`：完整实现上述契约。
- `game.js`：Canvas 渲染循环（像素风、星空视差背景、玩家/敌机/子弹绘制、HUD、键盘 ←/→/空格/R、game over 画面），从 `game-logic.js` import 逻辑。
- `index.html`：含 `<canvas id="game">` 与 `<script type="module" src="game.js">`。

## 仓库联动修改

| 文件 | 修改 |
| --- | --- |
| `benchmark/specs.json` | 新增 `write-plane-shooter` 隐藏检查 |
| `tests/test_benchmark.py` | case 数 13 → 14；`reference_files` 支持多文件映射并加入新 case（3 个文件） |
| `README.md` | case 总数 13 → 14；code_generation 3 → 4 并更新描述；ModelTest 权重 3/3/7 → 3/4/7 |
| `model_dashboard/server.py` | `MODEL_TEST_WEIGHTS["generation"]` 3 → 4 |
| `model_dashboard/static/index.html` | 权重展示 `"3 / 3 / 7"` → `"3 / 4 / 7"` |
| `tests/test_model_dashboard.py` | `model_test_total` 期望 93.08 → 93.57（(100*3 + 100*4 + 87.14*7) / 14） |

## 验证

- `python3 -m unittest discover -s tests -v`
- `python3 -m compileall -q benchmark model_dashboard tests run_benchmark.py`
- 新 case 目录用参考解覆盖后 `npm test`
- `benchmark.py prepare` + 参考解 + `grade` 冒烟：参考解应得 100 分
- `python3 benchmark.py list` 显示新 case

## 范围外（YAGNI）

- 不扩展评分器支持浏览器自动化。
- 不做难度递增、Boss、道具掉落、多种敌机（用户已选择的最小要素集）。
- 不修改 2.5D 等距渲染需求（打飞机为竖版 2D 像素风）。