export function pageWindow(current, total, size) {
  if (total <= 0 || size <= 0) return [];

  const clampedSize = Math.min(size, total);
  const clampedCurrent = Math.min(Math.max(current, 1), total);

  const idealStart = clampedCurrent - Math.floor(clampedSize / 2);
  const maxStart = total - clampedSize + 1;
  const start = Math.min(Math.max(idealStart, 1), maxStart);

  return Array.from({ length: clampedSize }, (_, index) => start + index);
}
