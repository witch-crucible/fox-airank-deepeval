export function toQueryString(params) {
  return Object.keys(params)
    .sort()
    .flatMap((key) => {
      const value = params[key];
      const values = Array.isArray(value) ? value : [value];

      return values
        .filter((item) => item !== null && item !== undefined)
        .map((item) => `${encodeURIComponent(key)}=${encodeURIComponent(item)}`);
    })
    .join("&");
}
