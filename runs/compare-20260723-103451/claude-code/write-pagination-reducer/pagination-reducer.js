function getLastPage(total, pageSize) {
  return Math.max(1, Math.ceil(total / pageSize));
}

export function paginationReducer(state, action) {
  switch (action.type) {
    case "SET_PAGE": {
      const lastPage = getLastPage(state.total, state.pageSize);
      const page = Math.min(Math.max(1, action.page), lastPage);
      return { ...state, page };
    }
    case "SET_PAGE_SIZE": {
      if (!Number.isInteger(action.pageSize) || action.pageSize <= 0) {
        return state;
      }
      const firstIndex = (state.page - 1) * state.pageSize;
      const lastPage = getLastPage(state.total, action.pageSize);
      const page = Math.min(Math.max(1, Math.floor(firstIndex / action.pageSize) + 1), lastPage);
      return { ...state, pageSize: action.pageSize, page };
    }
    case "SET_TOTAL": {
      const total = Math.max(0, Math.trunc(action.total));
      const lastPage = getLastPage(total, state.pageSize);
      const page = Math.min(state.page, lastPage);
      return { ...state, total, page };
    }
    case "RESET": {
      return { page: 1, pageSize: state.pageSize, total: 0 };
    }
    default:
      return state;
  }
}
