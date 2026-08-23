export function paginationReducer(state, action) {
  const lastPage = (total, pageSize) => Math.max(1, Math.ceil(total / pageSize));
  const clampPage = (page, total, pageSize) => Math.max(1, Math.min(Math.trunc(Number(page)) || 1, lastPage(total, pageSize)));
  if (action.type === "UNKNOWN") return state;
  if (action.type === "RESET") return { page: 1, pageSize: state.pageSize, total: 0 };
  if (action.type === "SET_PAGE") return { ...state, page: clampPage(action.page, state.total, state.pageSize) };
  if (action.type === "SET_PAGE_SIZE") {
    const pageSize = Number(action.pageSize);
    if (!Number.isInteger(pageSize) || pageSize <= 0) return state;
    const firstIndex = (state.page - 1) * state.pageSize;
    return { ...state, pageSize, page: clampPage(Math.floor(firstIndex / pageSize) + 1, state.total, pageSize) };
  }
  if (action.type === "SET_TOTAL") {
    const total = Math.max(0, Math.trunc(Number(action.total)) || 0);
    return { ...state, total, page: clampPage(state.page, total, state.pageSize) };
  }
  return state;
}
