export function toQueryString(params) {
  const parts = [];
  for (const key of Object.keys(params).sort()) {
    const value = params[key];
    if (value === null || value === undefined) {
      continue;
    }
    const encodedKey = encodeURIComponent(key);
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === null || item === undefined) {
          continue;
        }
        parts.push(`${encodedKey}=${encodeURIComponent(String(item))}`);
      }
    } else {
      parts.push(`${encodedKey}=${encodeURIComponent(String(value))}`);
    }
  }
  return parts.join("&");
}
