# 从购物车事件日志反推乱序缺陷

本 case 没有源码。阅读 `cart-events.json`：每条事件包含客户端发起顺序 `seq`、
事件类型 `type`（`add_item`/`remove_item`）、`item_id`，以及客户端发出时间
`sent_at` 与服务端收到时间 `received_at`。服务端按 `received_at` 到达顺序
应用事件来维护购物车状态。

请找出因为事件到达顺序与发起顺序不一致而导致的最终购物车状态错误，
统计受影响的"乱序事件对"数量与受影响的商品数量。

按 `RESULT_PROTOCOL.md` 生成 `result.json`，`answer` 必须严格为：

```json
{
  "process_issue": "固定问题标识",
  "evidence": {"out_of_order_pairs": 0, "affected_items": 0},
  "control": "固定措施标识"
}
```

问题标识只能是 `out-of-order-event-application`、
`duplicate-event-processing`、`missing-event-delivery`；措施标识只能是
`sequence-number-enforcement`、`idempotency-key-per-intent`、
`increase-timeout`。
