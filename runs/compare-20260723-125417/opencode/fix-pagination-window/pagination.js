export function pageWindow(current, total, size) {
  if (total <= 0 || size <= 0) return [];

  const clampedSize = Math.min(size, total);
  const clampedCurrent = Math.max(1, Math.min(current, total));

  // For even size, current sits at the right-of-center position.
  // offset = floor(size/2) gives right-of-center for even, center for odd.
  const offset = Math.floor(clampedSize / 2);
  let start = clampedCurrent - offset;

  // Clamp window to [1, total]
  if (start < 1) start = 1;
  if (start + clampedSize > total + 1) start = total - clampedSize + 1;

  return Array.from({ length: clampedSize }, (_, i) => start + i);
}
