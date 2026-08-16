# 从结果数据反推结账过程缺陷

本 case 没有源码。阅读 `checkout-run.json`，从结果之间的数量关系判断结账过程存在的核心问题及最直接的控制措施。不要把“接口调用多于意图”本身当成根因。

按 `RESULT_PROTOCOL.md` 生成 `result.json`，`answer` 必须严格为：

```json
{
  "process_issue": "固定问题标识",
  "evidence": {"duplicate_orders": 0, "retried_intents": 0},
  "control": "固定措施标识"
}
```

问题标识只能是 `retry-without-idempotency`、`lost-checkout-requests`、`incorrect-success-count`；措施标识只能是 `idempotency-key-per-intent`、`increase-timeout`、`client-side-counter`。
