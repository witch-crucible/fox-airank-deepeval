export function paginationReducer(state, action) {
  const lastPage = (total, pageSize) =>
    total > 0 ? Math.ceil(total / pageSize) : 1;

  switch (action.type) {
    case "SET_PAGE": {
      const page = Math.min(Math.max(action.page, 1), lastPage(state.total, state.pageSize));
      return { ...state, page };
    }
    case "SET_PAGE_SIZE": {
      const pageSize = action.pageSize;
      if (!Number.isInteger(pageSize) || pageSize <= 0) return state;
      const firstIndex = (state.page - 1) * state.pageSize;
      const page = Math.min(
        Math.floor(firstIndex / pageSize) + 1,
        lastPage(state.total, pageSize)
      );
      return { ...state, page, pageSize };
    }
    case "SET_TOTAL": {
      const total = Number.isInteger(action.total) && action.total > 0 ? action.total : 0;
      const page = Math.min(state.page, lastPage(total, state.pageSize));
      return { ...state, page, total };
    }
    case "RESET":
      return { page: 1, pageSize: state.pageSize, total: 0 };
    default:
      return state;
  }
}
