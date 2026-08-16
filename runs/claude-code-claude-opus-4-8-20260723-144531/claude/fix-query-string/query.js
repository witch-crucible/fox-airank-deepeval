export function toQueryString(params) {
  return Object.keys(params)
    .sort()
    .flatMap((key) => {
      const value = params[key];
      if (value === null || value === undefined) {
        return [];
      }
      const values = Array.isArray(value) ? value : [value];
      return values.map(
        (item) => `${encodeURIComponent(key)}=${encodeURIComponent(item)}`
      );
    })
    .join("&");
}
