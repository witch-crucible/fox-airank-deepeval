export function pageWindow(current, total, size) {
  if (total <= 0 || size <= 0) return [];
  const length = Math.min(size, total);
  current = Math.min(Math.max(current, 1), total);
  let start = current - Math.floor(length / 2);
  start = Math.min(start, total - length + 1);
  start = Math.max(1, start);
  return Array.from({ length }, (_, index) => start + index);
}
