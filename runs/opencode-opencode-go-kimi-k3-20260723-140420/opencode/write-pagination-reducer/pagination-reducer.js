function lastPage(total, pageSize) {
  return Math.max(1, Math.ceil(total / pageSize));
}

export function paginationReducer(state, action) {
  switch (action.type) {
    case "SET_PAGE": {
      const page = Math.min(Math.max(1, action.page), lastPage(state.total, state.pageSize));
      return { ...state, page };
    }
    case "SET_PAGE_SIZE": {
      const pageSize = action.pageSize;
      if (!Number.isInteger(pageSize) || pageSize <= 0) {
        return state;
      }
      const firstIndex = (state.page - 1) * state.pageSize;
      const page = Math.min(Math.floor(firstIndex / pageSize) + 1, lastPage(state.total, pageSize));
      return { ...state, page, pageSize };
    }
    case "SET_TOTAL": {
      const total = Math.max(0, Math.floor(action.total));
      const page = Math.min(state.page, lastPage(total, state.pageSize));
      return { ...state, page, total };
    }
    case "RESET":
      return { page: 1, pageSize: state.pageSize, total: 0 };
    default:
      return state;
  }
}
