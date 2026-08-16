# 实现分页状态 reducer

在 `pagination-reducer.js` 实现 `paginationReducer(state, action)`：

- `SET_PAGE`：将 page 限制在 1 到根据 total/pageSize 计算的最后一页；无数据时最后一页仍为 1。
- `SET_PAGE_SIZE`：pageSize 必须为正整数，否则返回原 state；有效时保持当前第一条记录的零基下标尽量不变，重新计算 page。
- `SET_TOTAL`：total 限制为非负整数，并在必要时向前修正 page。
- `RESET`：返回 `{ page: 1, pageSize: state.pageSize, total: 0 }`。
- 未知 action 返回原 state 对象；有效 action 返回新对象；不得修改输入。

执行 `npm test`，并按 `RESULT_PROTOCOL.md` 生成 `result.json`。
