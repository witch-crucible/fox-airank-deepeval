// 构建：tsc 编译 TS → 将 dist 产物内联进 template → 输出自包含 index.html
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const PLACEHOLDER = "/*__BUNDLE__*/";

function fail(step, message) {
  throw new Error(`[build:${step}] ${message}`);
}

function countOccurrences(haystack, needle) {
  return haystack.split(needle).length - 1;
}

let order;
try {
  order = ["sim.js", "render.js", "main.js"];
  const missing = order.filter((f) => !existsSync(join(root, "dist", f)));
  if (missing.length > 0) {
    fail("resolve", `dist 产物缺失: ${missing.join(", ")}（是否忘记先跑 tsc？）`);
  }
} catch (err) {
  if (err.message.startsWith("[build:")) throw err;
  fail("resolve", `解析产物顺序失败: ${err.message}`);
}

try {
  const tscBin = join(root, "node_modules", ".bin", process.platform === "win32" ? "tsc.cmd" : "tsc");
  execFileSync(tscBin, ["-p", join(root, "tsconfig.json")], { stdio: "inherit", shell: process.platform === "win32" });
} catch (err) {
  fail("tsc", `TypeScript 编译失败: ${err.message}`);
}

let bundle;
try {
  bundle = order
    .map((f) => {
      try {
        return readFileSync(join(root, "dist", f), "utf8");
      } catch (err) {
        fail("read", `读取 ${join("dist", f)} 失败: ${err.message}`);
      }
    })
    .join("\n;\n");
} catch (err) {
  if (err.message.startsWith("[build:")) throw err;
  fail("concat", `拼接 bundle 失败: ${err.message}`);
}
if (!bundle.trim()) fail("concat", "拼接后的 bundle 为空，dist 产物可能全部为空文件");

// 内联到 <script> 时必须转义，否则 bundle 中的 "</script>" 会提前闭合标签并破坏页面。
bundle = bundle.replace(/<\/script>/gi, "<\\/script>");

let template;
try {
  template = readFileSync(join(root, "src", "template.html"), "utf8");
} catch (err) {
  fail("template", `读取 src/template.html 失败: ${err.message}`);
}
const hits = countOccurrences(template, PLACEHOLDER);
if (hits === 0) fail("template", "模板缺少 __BUNDLE__ 占位符");
if (hits > 1) fail("template", `模板中 __BUNDLE__ 占位符出现 ${hits} 次，应恰好 1 次（否则残留占位符会静默输出空舞台）`);
const html = template.replace(PLACEHOLDER, () => bundle);
if (html.includes(PLACEHOLDER)) fail("inline", "内联后仍残留 __BUNDLE__ 占位符");

try {
  writeFileSync(join(root, "index.html"), html, "utf8");
} catch (err) {
  fail("write", `写入 index.html 失败: ${err.message}`);
}
console.log(`构建完成：index.html（内联 ${(bundle.length / 1024).toFixed(1)} KB JS）`);
