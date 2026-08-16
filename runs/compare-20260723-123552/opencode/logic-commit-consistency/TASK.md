# 检查 commit 声明与代码变更一致性

阅读 `COMMIT_MESSAGE.txt` 和 `change.diff`，判断提交内容是否完整实现 commit 声明。只评价声明覆盖的行为，不提出无关重构。

按 `RESULT_PROTOCOL.md` 生成 `result.json`，`answer` 必须严格为：

```json
{
  "consistent": false,
  "implemented_dimensions": ["维度名"],
  "missing_dimensions": ["维度名"],
  "risk": "none 或固定风险标识"
}
```

维度名只能使用 `currency`、`locale`；风险标识只能使用 `none`、`cross-currency-cache-collision`、`cross-locale-cache-collision`。
