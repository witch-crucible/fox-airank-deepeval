# 结果文件协议

完成任务后，在当前目录生成 `result.json`：

```json
{
  "case_id": "logic-fragmented-business-rule",
  "status": "completed",
  "summary": "实际完成内容",
  "changed_files": ["实际修改或新增的相对路径"],
  "verification": ["实际执行的验证命令或检查"]
}
```

不得伪造未执行的验证。逻辑题还必须保留 TASK.md 要求的 `answer` 字段。
