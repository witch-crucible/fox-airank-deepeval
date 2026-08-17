import assert from "node:assert/strict";
import { createGameState, movePlayer, shoot, update } from "./game-logic.js";

const s = createGameState({ width: 400, height: 600, random: () => 0.5 });
assert.equal(s.player.lives, 3);
assert.equal(s.status, "playing");
movePlayer(s, -999);
assert.equal(s.player.x, 0);
shoot(s);
assert.equal(s.bullets.length, 1);
s.enemies.push({ x: s.bullets[0].x, y: s.bullets[0].y, w: 32, h: 32, speed: 0, score: 10 });
update(s, 0.016);
assert.equal(s.score, 10);
console.log("public test passed");