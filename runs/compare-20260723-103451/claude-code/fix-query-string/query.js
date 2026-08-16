export function toQueryString(params) {
  return Object.keys(params)
    .sort()
    .flatMap((key) => {
      const value = params[key];
      if (value === null || value === undefined) return [];
      const encodedKey = encodeURIComponent(key);
      if (Array.isArray(value)) {
        return value.map((item) => `${encodedKey}=${encodeURIComponent(item)}`);
      }
      return [`${encodedKey}=${encodeURIComponent(value)}`];
    })
    .join("&");
}
