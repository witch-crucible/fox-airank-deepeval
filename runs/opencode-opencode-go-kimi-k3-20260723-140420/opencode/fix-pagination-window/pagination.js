export function pageWindow(current, total, size) {
  if (total <= 0 || size <= 0) {
    return [];
  }
  const windowSize = Math.min(size, total);
  const clampedCurrent = Math.min(Math.max(1, current), total);
  let start = clampedCurrent - Math.floor(windowSize / 2);
  start = Math.max(1, Math.min(start, total - windowSize + 1));
  return Array.from({ length: windowSize }, (_, index) => start + index);
}
