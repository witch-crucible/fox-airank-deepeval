export function pageWindow(current, total, size) {
  if (total <= 0 || size <= 0) {
    return [];
  }
  const windowSize = Math.min(size, total);
  const clampedCurrent = Math.min(Math.max(current, 1), total);
  const maxStart = total - windowSize + 1;
  const start = Math.min(
    Math.max(1, clampedCurrent - Math.floor(windowSize / 2)),
    maxStart,
  );
  return Array.from({ length: windowSize }, (_, index) => start + index);
}
