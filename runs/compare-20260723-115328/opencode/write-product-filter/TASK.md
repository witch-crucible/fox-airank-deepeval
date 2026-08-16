# 实现商品筛选与稳定排序

在 `product-filter.js` 实现 `filterProducts(products, options)`：

- options 可含 `query`、`categories`、`minPrice`、`maxPrice`、`inStockOnly`、`sortBy`。
- query 去除首尾空格并忽略大小写，同时匹配 name 或 sku；categories 为空时不过滤，否则精确匹配分类。
- 价格边界包含端点；`inStockOnly` 仅保留 stock > 0。
- sortBy 支持 `price-asc`、`price-desc`、`name-asc`，未提供时保持原顺序；值相等时保持原始顺序。
- 不得修改 products、options 或其中对象，返回新数组。

只使用标准 JavaScript。执行 `npm test`，并按 `RESULT_PROTOCOL.md` 生成 `result.json`。
