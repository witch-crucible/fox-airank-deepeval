export function paginationReducer(state, action) {
  switch (action.type) {
    case "SET_PAGE": {
      const maxPage = state.total > 0 ? Math.ceil(state.total / state.pageSize) : 1;
      const page = Math.max(1, Math.min(action.page, maxPage));
      return { ...state, page };
    }
    case "SET_PAGE_SIZE": {
      if (!Number.isInteger(action.pageSize) || action.pageSize <= 0) return state;
      const firstIndex = (state.page - 1) * state.pageSize;
      const newPage = Math.floor(firstIndex / action.pageSize) + 1;
      const maxPage = state.total > 0 ? Math.ceil(state.total / action.pageSize) : 1;
      const page = Math.min(newPage, maxPage);
      return { ...state, pageSize: action.pageSize, page };
    }
    case "SET_TOTAL": {
      const total = Math.max(0, Math.floor(action.total));
      const maxPage = total > 0 ? Math.ceil(total / state.pageSize) : 1;
      const page = Math.min(state.page, maxPage);
      return { ...state, total, page };
    }
    case "RESET":
      return { page: 1, pageSize: state.pageSize, total: 0 };
    default:
      return state;
  }
}
