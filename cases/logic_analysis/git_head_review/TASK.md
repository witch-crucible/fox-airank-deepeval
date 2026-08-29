# 审查子 Git 项目的 HEAD 提交

`permission-cache/` 是一个独立 Git 项目。审查它的 HEAD 提交，结合提交声明、相对父提交的代码变更和当前实现，判断声明的保证是否全部实现。不要修改项目代码，只评价 HEAD 声明覆盖的行为。

按 `RESULT_PROTOCOL.md` 生成 `result.json`，`answer` 必须严格为：

```json
{
  "commit_subject": "HEAD 的完整 subject",
  "consistent": false,
  "implemented_guarantees": ["保证标识"],
  "missing_guarantees": ["保证标识"],
  "risk": "none 或固定风险标识"
}
```

保证标识只能使用 `tenant-isolation`、`role-version-invalidation`；风险标识只能使用 `none`、`cross-tenant-permission-reuse`、`stale-permission-after-role-change`。
