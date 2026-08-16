export function toQueryString(params) {
  const parts = [];

  for (const key of Object.keys(params).sort()) {
    const value = params[key];
    const values = Array.isArray(value) ? value : [value];

    for (const item of values) {
      if (item !== null && item !== undefined) {
        parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(item)}`);
      }
    }
  }

  return parts.join("&");
}
