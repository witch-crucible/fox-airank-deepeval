import assert from "node:assert/strict";
import { renderProductCard } from "./product-card.js";

const html = renderProductCard({ sku: "A", imageUrl: "/a.jpg", name: "Lady Dior", price: 32000, description: "Bag", stock: 1 });
assert.match(html, /<article class="product-card"/);
assert.match(html, /加入购物车/);
console.log("public test passed");
