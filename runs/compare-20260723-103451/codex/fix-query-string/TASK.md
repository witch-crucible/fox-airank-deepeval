# 修复查询参数序列化

修复 `query.js` 的 `toQueryString(params)`：

- 忽略值为 `null` 或 `undefined` 的字段，但保留 `false`、`0` 和空字符串。
- 数组为每个元素生成一个同名参数；空数组不生成参数。
- key 和 value 必须使用 `encodeURIComponent` 编码。
- 对象自身 key 按字典序处理；不得修改输入。

保持函数签名，只使用标准 JavaScript。执行 `npm test`，并按 `RESULT_PROTOCOL.md` 生成 `result.json`。
