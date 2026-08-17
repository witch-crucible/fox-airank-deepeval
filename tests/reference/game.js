import { createGameState, movePlayer, shoot, update, restart } from "./game-logic.js";

const canvas = document.getElementById("game");
const ctx = canvas.getContext("2d");

const state = createGameState({ width: canvas.width, height: canvas.height });

const keys = { left: false, right: false, fire: false };
const STAR_COUNT = 60;
const stars = Array.from({ length: STAR_COUNT }, () => ({
  x: Math.random() * canvas.width,
  y: Math.random() * canvas.height,
  speed: 40 + Math.random() * 100,
  size: Math.random() < 0.8 ? 1 : 2,
}));

window.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft" || event.key === "a" || event.key === "A") keys.left = true;
  if (event.key === "ArrowRight" || event.key === "d" || event.key === "D") keys.right = true;
  if (event.key === " ") keys.fire = true;
  if (event.key === "r" || event.key === "R") restart(state);
  if (["ArrowLeft", "ArrowRight", " ", "r", "R", "a", "A", "d", "D"].includes(event.key)) {
    event.preventDefault();
  }
});

window.addEventListener("keyup", (event) => {
  if (event.key === "ArrowLeft" || event.key === "a" || event.key === "A") keys.left = false;
  if (event.key === "ArrowRight" || event.key === "d" || event.key === "D") keys.right = false;
  if (event.key === " ") keys.fire = false;
});

function drawPlayer() {
  const { x, y, w, h } = state.player;
  ctx.fillStyle = "#7ee787";
  ctx.fillRect(x + w / 2 - 2, y, 4, 6);
  ctx.fillStyle = "#58a6ff";
  ctx.fillRect(x + 2, y + 6, w - 4, h - 12);
  ctx.fillStyle = "#9cdcfe";
  ctx.fillRect(x + 8, y + 10, 4, h - 18);
  ctx.fillRect(x + w - 12, y + 10, 4, h - 18);
  ctx.fillStyle = "#e6edf3";
  ctx.fillRect(x + 4, y + h - 6, w - 8, 4);
}

function drawEnemy(enemy) {
  ctx.fillStyle = "#ff7b72";
  ctx.fillRect(enemy.x, enemy.y, enemy.w, enemy.h);
  ctx.fillStyle = "#da3633";
  ctx.fillRect(enemy.x + 4, enemy.y + 8, enemy.w - 8, enemy.h - 16);
  ctx.fillStyle = "#ffa198";
  ctx.fillRect(enemy.x + 8, enemy.y + 6, 4, 6);
  ctx.fillRect(enemy.x + enemy.w - 12, enemy.y + 6, 4, 6);
}

function drawBullets() {
  ctx.fillStyle = "#f0883e";
  for (const bullet of state.bullets) {
    ctx.fillRect(bullet.x, bullet.y, bullet.w, bullet.h);
  }
}

function drawStars(dt) {
  for (const star of stars) {
    star.y += star.speed * dt;
    if (star.y > canvas.height) {
      star.y = -2;
      star.x = Math.random() * canvas.width;
    }
    ctx.fillStyle = star.size > 1 ? "#8b949e" : "#3d4a63";
    ctx.fillRect(star.x, star.y, star.size, star.size);
  }
}

function drawHUD() {
  ctx.font = "16px monospace";
  ctx.textBaseline = "top";
  ctx.fillStyle = "#e6edf3";
  ctx.fillText(`SCORE ${state.score}`, 8, 8);
  ctx.fillStyle = "#ff7b72";
  ctx.fillText(`LIVES ${state.player.lives}`, canvas.width - 96, 8);
}

function drawGameOver() {
  ctx.fillStyle = "rgba(5, 7, 15, 0.75)";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#ff7b72";
  ctx.font = "32px monospace";
  ctx.textAlign = "center";
  ctx.fillText("GAME OVER", canvas.width / 2, canvas.height / 2 - 16);
  ctx.fillStyle = "#e6edf3";
  ctx.font = "16px monospace";
  ctx.fillText("按 R 重新开始", canvas.width / 2, canvas.height / 2 + 16);
  ctx.textAlign = "left";
}

let lastTime = 0;
function frame(time) {
  const dt = Math.min((time - lastTime) / 1000, 0.05);
  lastTime = time;

  if (keys.left) movePlayer(state, -260 * dt);
  if (keys.right) movePlayer(state, 260 * dt);
  if (keys.fire) shoot(state);
  update(state, dt);

  ctx.fillStyle = "#05070f";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  drawStars(dt);
  drawBullets();
  for (const enemy of state.enemies) drawEnemy(enemy);
  drawPlayer();
  drawHUD();
  if (state.status === "gameover") drawGameOver();

  requestAnimationFrame(frame);
}

requestAnimationFrame(frame);