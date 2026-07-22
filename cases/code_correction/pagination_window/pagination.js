export function pageWindow(current, total, size) {
  const start = Math.max(1, current - Math.floor(size / 2));
  const end = Math.min(total, start + size);
  return Array.from({ length: end - start }, (_, index) => start + index);
}
