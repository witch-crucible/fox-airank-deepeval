# 修复分页窗口边界

修复 `pagination.js` 的 `pageWindow(current, total, size)`，返回连续页码数组：

- total 或 size 小于等于 0 时返回空数组。
- current 限制到 `[1, total]`，size 最多为 total。
- 尽量让 current 居中；靠近两端时平移窗口以保持目标长度。
- size 为偶数时，current 位于中间两个位置中靠右的位置。例如 `pageWindow(5, 10, 4)` 返回 `[3,4,5,6]`。

保持函数签名。执行 `npm test`，并按 `RESULT_PROTOCOL.md` 生成 `result.json`。
