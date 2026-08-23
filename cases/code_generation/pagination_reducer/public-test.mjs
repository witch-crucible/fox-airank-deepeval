import assert from "node:assert/strict";
import { paginationReducer } from "./pagination-reducer.js";

assert.deepEqual(paginationReducer({ page: 2, pageSize: 10, total: 35 }, { type: "SET_PAGE", page: 9 }), {
  page: 4, pageSize: 10, total: 35
});
assert.deepEqual(paginationReducer({ page: 3, pageSize: 10, total: 100 }, { type: "SET_PAGE_SIZE", pageSize: 25 }), {
  page: 1, pageSize: 25, total: 100
});
console.log("public test passed");
