export function pageWindow(current, total, size) {
  if (total <= 0 || size <= 0) {
    return [];
  }

  const windowSize = Math.min(size, total);
  const currentPage = Math.min(Math.max(current, 1), total);
  const centeredStart = currentPage - Math.floor(windowSize / 2);
  const start = Math.min(
    Math.max(centeredStart, 1),
    total - windowSize + 1,
  );

  return Array.from({ length: windowSize }, (_, index) => start + index);
}
