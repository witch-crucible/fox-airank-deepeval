# 修复购物车金额计算

修复 `cart.js` 的 `calculateCart`。要求：

- 忽略数量小于等于 0 的商品；价格和数量均按整数处理。
- subtotal 是有效商品的 `price * quantity` 之和。
- 百分比优惠券只对 subtotal 生效，折扣四舍五入到最近整数；百分比限制在 0 到 100。
- shippingThreshold 判断基于折后金额：达到阈值免运费，否则收 shippingFee。
- total 不能小于 0，且不得修改输入对象。

保持函数签名和返回字段。执行 `npm test`，并按 `RESULT_PROTOCOL.md` 生成 `result.json`。
