import assert from "node:assert/strict";
import { pageWindow } from "./pagination.js";

assert.deepEqual(pageWindow(5, 10, 5), [3, 4, 5, 6, 7]);
console.log("public test passed");
