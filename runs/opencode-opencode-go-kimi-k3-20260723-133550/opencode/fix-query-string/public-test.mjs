import assert from "node:assert/strict";
import { toQueryString } from "./query.js";

assert.equal(toQueryString({ page: 2, q: "dior bag" }), "page=2&q=dior%20bag");
console.log("public test passed");

