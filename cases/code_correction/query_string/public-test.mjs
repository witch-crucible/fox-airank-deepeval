import assert from "node:assert/strict";
import { toQueryString } from "./query.js";

assert.equal(toQueryString({ page: 2, q: "dior bag" }), "page=2&q=dior%20bag");
assert.equal(toQueryString({ page: 0, active: false, q: "a&b=c" }), "page=0&active=false&q=a%26b%3Dc");
console.log("public test passed");
