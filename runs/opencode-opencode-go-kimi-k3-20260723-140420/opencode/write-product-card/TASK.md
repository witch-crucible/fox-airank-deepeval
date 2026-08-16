# 实现安全且可访问的商品卡片

在 `product-card.js` 实现 `renderProductCard(product)`，返回单个商品卡片 HTML 字符串：

- 根元素为 `<article class="product-card" data-sku="...">`。
- 包含图片 `<img>`，src 为 imageUrl，alt 为产品 name。
- 产品名使用 `<h2>`；价格显示为 `¥` 加整数价格；描述使用 `<p>`。
- 有库存时按钮文本为“加入购物车”，并带 `data-action="add-to-cart"`；无库存时按钮文本为“暂时缺货”且具有 `disabled` 属性。
- sku、imageUrl、name、description 中的 `& < > \" '` 必须进行 HTML 属性/文本安全转义。

不要使用 DOM 或第三方库。执行 `npm test`，并按 `RESULT_PROTOCOL.md` 生成 `result.json`。
