function pages(total, pageSize) {
  return Math.max(1, Math.ceil(total / pageSize));
}

export function paginationReducer(state, action) {
  if (action.type === "SET_PAGE") {
    const page = Math.min(pages(state.total, state.pageSize), Math.max(1, Math.trunc(action.page)));
    return { ...state, page };
  }
  if (action.type === "SET_PAGE_SIZE") {
    if (!Number.isInteger(action.pageSize) || action.pageSize <= 0) return state;
    const firstIndex = (state.page - 1) * state.pageSize;
    const page = Math.min(pages(state.total, action.pageSize), Math.floor(firstIndex / action.pageSize) + 1);
    return { ...state, page, pageSize: action.pageSize };
  }
  if (action.type === "SET_TOTAL") {
    const total = Math.max(0, Math.trunc(action.total));
    return { ...state, total, page: Math.min(state.page, pages(total, state.pageSize)) };
  }
  if (action.type === "RESET") return { page: 1, pageSize: state.pageSize, total: 0 };
  return state;
}
