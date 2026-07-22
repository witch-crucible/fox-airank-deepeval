export function pageWindow(current, total, size) {
  if (total <= 0 || size <= 0) {
    return [];
  }

  const windowSize = Math.min(size, total);
  const currentPage = Math.min(total, Math.max(1, current));
  const centeredStart = currentPage - Math.floor(windowSize / 2);
  const start = Math.max(1, Math.min(centeredStart, total - windowSize + 1));

  return Array.from({ length: windowSize }, (_, index) => start + index);
}
