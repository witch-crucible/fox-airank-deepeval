export function paginationReducer(state, action) {
  const lastPage = (total, pageSize) =>
    Math.max(1, Math.ceil(total / pageSize));

  switch (action.type) {
    case "SET_PAGE": {
      const requestedPage = Number.isFinite(action.page)
        ? Math.trunc(action.page)
        : 1;
      return {
        ...state,
        page: Math.min(
          Math.max(1, requestedPage),
          lastPage(state.total, state.pageSize),
        ),
      };
    }
    case "SET_PAGE_SIZE": {
      if (!Number.isInteger(action.pageSize) || action.pageSize <= 0) {
        return state;
      }

      const firstItemIndex = (state.page - 1) * state.pageSize;
      const page = Math.floor(firstItemIndex / action.pageSize) + 1;
      return {
        ...state,
        page: Math.min(page, lastPage(state.total, action.pageSize)),
        pageSize: action.pageSize,
      };
    }
    case "SET_TOTAL": {
      const total = Number.isFinite(action.total)
        ? Math.max(0, Math.trunc(action.total))
        : 0;
      return {
        ...state,
        page: Math.min(state.page, lastPage(total, state.pageSize)),
        total,
      };
    }
    case "RESET":
      return { page: 1, pageSize: state.pageSize, total: 0 };
    default:
      return state;
  }
}
