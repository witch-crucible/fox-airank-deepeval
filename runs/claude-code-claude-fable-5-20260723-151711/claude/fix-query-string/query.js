export function toQueryString(params) {
  const pairs = [];
  for (const key of Object.keys(params).sort()) {
    const value = params[key];
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(item)}`);
      }
    } else {
      pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
    }
  }
  return pairs.join("&");
}
