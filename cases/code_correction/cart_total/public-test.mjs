import assert from "node:assert/strict";
import { calculateCart } from "./cart.js";

assert.deepEqual(calculateCart([{ price: 100, quantity: 2 }], null, 300, 20), {
  subtotal: 200, discount: 0, shipping: 20, total: 220
});
assert.deepEqual(calculateCart([{ price: 100, quantity: 2 }], { percent: 2 }, 0, 20), {
  subtotal: 200, discount: 200, shipping: 0, total: 0
});
console.log("public test passed");
