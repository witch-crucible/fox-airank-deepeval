export function toQueryString(params) {
  const keys = Object.keys(params).sort();
  const parts = [];

  for (const key of keys) {
    const value = params[key];
    if (value === null || value === undefined) continue;

    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      for (const item of value) {
        parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(item)}`);
      }
    } else if (value === false || value === 0 || value === "" || value) {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
    }
  }

  return parts.join("&");
}
