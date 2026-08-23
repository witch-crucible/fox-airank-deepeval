import { createGameState, movePlayer, shoot, update, restart } from "./game-logic.js";

const canvas = document.getElementById("game"), ctx = canvas.getContext("2d");
const state = createGameState({ width: canvas.width, height: canvas.height });
const keys = { left: false, right: false, fire: false };
addEventListener("keydown", event => { if (event.key === "ArrowLeft" || event.key.toLowerCase() === "a") keys.left = true; if (event.key === "ArrowRight" || event.key.toLowerCase() === "d") keys.right = true; if (event.key === " ") keys.fire = true; if (event.key.toLowerCase() === "r") restart(state); });
addEventListener("keyup", event => { if (event.key === "ArrowLeft" || event.key.toLowerCase() === "a") keys.left = false; if (event.key === "ArrowRight" || event.key.toLowerCase() === "d") keys.right = false; if (event.key === " ") keys.fire = false; });
let last = 0;
function frame(time) {
  const dt = Math.min((time - last) / 1000, 0.05); last = time;
  if (keys.left) movePlayer(state, -260 * dt); if (keys.right) movePlayer(state, 260 * dt); if (keys.fire) shoot(state); update(state, dt);
  ctx.fillStyle = "#05070f"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#58a6ff"; ctx.fillRect(state.player.x, state.player.y, state.player.w, state.player.h);
  ctx.fillStyle = "#f0883e"; state.bullets.forEach(b => ctx.fillRect(b.x, b.y, b.w, b.h));
  ctx.fillStyle = "#ff7b72"; state.enemies.forEach(e => ctx.fillRect(e.x, e.y, e.w, e.h));
  ctx.fillStyle = "#e6edf3"; ctx.font = "16px monospace"; ctx.fillText(`SCORE ${state.score}  LIVES ${state.player.lives}`, 8, 20);
  if (state.status === "gameover") { ctx.textAlign = "center"; ctx.fillText("GAME OVER — 按 R 重新开始", canvas.width / 2, canvas.height / 2); ctx.textAlign = "left"; }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
