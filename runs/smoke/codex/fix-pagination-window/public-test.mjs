import assert from "node:assert/strict";
import { pageWindow } from "./pagination.js";

assert.deepEqual(pageWindow(5, 10, 5), [3, 4, 5, 6, 7]);
assert.deepEqual(pageWindow(5, 10, 4), [3, 4, 5, 6]);
assert.deepEqual(pageWindow(10, 10, 5), [6, 7, 8, 9, 10]);
assert.deepEqual(pageWindow(0, 10, 5), [1, 2, 3, 4, 5]);
assert.deepEqual(pageWindow(12, 10, 4), [7, 8, 9, 10]);
assert.deepEqual(pageWindow(5, 3, 10), [1, 2, 3]);
assert.deepEqual(pageWindow(1, 0, 5), []);
assert.deepEqual(pageWindow(1, 5, 0), []);
console.log("public test passed");
