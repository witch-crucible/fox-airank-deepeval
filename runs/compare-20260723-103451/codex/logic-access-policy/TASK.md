# 检查访问策略声明与实现是否一致

阅读 `ACCESS_POLICY.md` 和 `permissions.js`，判断实现是否完全符合策略声明。
只指出策略明确覆盖的行为，不提出无关重构。

按 `RESULT_PROTOCOL.md` 生成 `result.json`，`answer` 必须严格为：

```json
{
  "policy_matches_implementation": false,
  "violating_role": "角色标识",
  "violating_status": "订单状态标识",
  "violating_action": "操作标识",
  "risk": "固定风险标识"
}
```

`violating_role` 只能是 `editor`、`reviewer`、`admin`；`violating_status`
只能是 `draft`、`submitted`、`archived`；`violating_action` 只能是 `view`、
`edit`；`risk` 只能是 `unauthorized-edit-of-submitted-order`。
