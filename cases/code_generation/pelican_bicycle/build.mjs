// 构建：tsc 编译 TS → 将 dist 产物内联进 template → 输出自包含 index.html
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
execFileSync(join(root, "node_modules", ".bin", "tsc"), ["-p", join(root, "tsconfig.json")], { stdio: "inherit" });

const order = ["sim.js", "render.js", "main.js"];
const bundle = order.map((f) => readFileSync(join(root, "dist", f), "utf8")).join("\n;\n");

const template = readFileSync(join(root, "src", "template.html"), "utf8");
if (!template.includes("/*__BUNDLE__*/")) throw new Error("模板缺少 __BUNDLE__ 占位符");
const html = template.replace("/*__BUNDLE__*/", () => bundle);
mkdirSync(root, { recursive: true });
writeFileSync(join(root, "index.html"), html, "utf8");
console.log(`构建完成：index.html（内联 ${(bundle.length / 1024).toFixed(1)} KB JS）`);
