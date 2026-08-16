export function pageWindow(current, total, size) {
  if (total <= 0 || size <= 0) {
    return [];
  }
  size = Math.min(size, total);
  current = Math.min(Math.max(current, 1), total);
  const start = Math.min(Math.max(current - Math.floor(size / 2), 1), total - size + 1);
  return Array.from({ length: size }, (_, index) => start + index);
}
