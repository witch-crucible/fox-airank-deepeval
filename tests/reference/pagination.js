export function pageWindow(current, total, size) {
  if (total <= 0 || size <= 0) return [];
  const length = Math.min(Math.trunc(size), Math.trunc(total));
  const page = Math.min(Math.trunc(total), Math.max(1, Math.trunc(current)));
  let start = page - Math.floor(length / 2);
  start = Math.max(1, Math.min(start, total - length + 1));
  return Array.from({ length }, (_, index) => start + index);
}
