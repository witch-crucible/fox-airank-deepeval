export function paginationReducer(state, action) {
  const lastPage = (total, pageSize) => Math.max(1, Math.ceil(total / pageSize));
  const clampPage = (page, total, pageSize) => {
    const integerPage = Number.isFinite(page) ? Math.trunc(page) : 1;
    return Math.min(Math.max(integerPage, 1), lastPage(total, pageSize));
  };

  switch (action.type) {
    case "SET_PAGE":
      return {
        ...state,
        page: clampPage(action.page, state.total, state.pageSize),
      };

    case "SET_PAGE_SIZE": {
      if (!Number.isInteger(action.pageSize) || action.pageSize <= 0) {
        return state;
      }

      const firstItemIndex = (state.page - 1) * state.pageSize;
      const page = Math.floor(firstItemIndex / action.pageSize) + 1;

      return {
        ...state,
        page: clampPage(page, state.total, action.pageSize),
        pageSize: action.pageSize,
      };
    }

    case "SET_TOTAL": {
      const total = Number.isFinite(action.total)
        ? Math.max(0, Math.floor(action.total))
        : 0;

      return {
        ...state,
        page: clampPage(state.page, total, state.pageSize),
        total,
      };
    }

    case "RESET":
      return { page: 1, pageSize: state.pageSize, total: 0 };

    default:
      return state;
  }
}
