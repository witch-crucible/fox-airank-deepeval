import assert from "node:assert/strict";
import { calculateCart } from "./cart.js";

assert.deepEqual(calculateCart([{ price: 100, quantity: 2 }], null, 300, 20), {
  subtotal: 200, discount: 0, shipping: 20, total: 220
});
console.log("public test passed");

