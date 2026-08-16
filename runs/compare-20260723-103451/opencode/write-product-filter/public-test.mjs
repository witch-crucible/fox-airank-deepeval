import assert from "node:assert/strict";
import { filterProducts } from "./product-filter.js";

const products = [
  { sku: "BAG-1", name: "Saddle Bag", category: "bag", price: 100, stock: 2 },
  { sku: "SCARF-1", name: "Silk Scarf", category: "scarf", price: 50, stock: 0 }
];
assert.deepEqual(filterProducts(products, { query: "bag" }), [products[0]]);
console.log("public test passed");

