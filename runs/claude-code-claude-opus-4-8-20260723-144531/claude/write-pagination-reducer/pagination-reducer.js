function lastPage(total, pageSize) {
  return Math.max(1, Math.ceil(total / pageSize));
}

export function paginationReducer(state, action) {
  switch (action.type) {
    case "SET_PAGE": {
      const last = lastPage(state.total, state.pageSize);
      const page = Math.min(Math.max(1, action.page), last);
      return { page, pageSize: state.pageSize, total: state.total };
    }
    case "SET_PAGE_SIZE": {
      if (!Number.isInteger(action.pageSize) || action.pageSize <= 0) {
        return state;
      }
      const firstIndex = (state.page - 1) * state.pageSize;
      const pageSize = action.pageSize;
      const last = lastPage(state.total, pageSize);
      const page = Math.min(Math.max(1, Math.floor(firstIndex / pageSize) + 1), last);
      return { page, pageSize, total: state.total };
    }
    case "SET_TOTAL": {
      if (typeof action.total !== "number" || !Number.isFinite(action.total)) {
        return state;
      }
      const total = Math.max(0, Math.floor(action.total));
      const page = Math.min(state.page, lastPage(total, state.pageSize));
      return { page, pageSize: state.pageSize, total };
    }
    case "RESET": {
      return { page: 1, pageSize: state.pageSize, total: 0 };
    }
    default:
      return state;
  }
}
