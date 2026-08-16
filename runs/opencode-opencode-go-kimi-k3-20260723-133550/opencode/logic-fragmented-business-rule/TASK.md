# 从零散描述还原运费业务规则

产品需求没有完整文档，只有 `fragments.md` 中的零散沟通记录。请综合全部信息，还原当前有效规则，并计算 `orders.json` 中每个订单的运费。不得自行补充规则。

按 `RESULT_PROTOCOL.md` 生成 `result.json`，`answer` 必须严格为：

```json
{
  "threshold_basis": "subtotal 或 after_discount",
  "mainland_threshold": 0,
  "mainland_standard_shipping": 0,
  "vip_mainland_free": true,
  "overseas_shipping": 0,
  "orders": {"订单ID": 0}
}
```
