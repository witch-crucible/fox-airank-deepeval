export function filterProducts(products, options = {}) {
  const { query, categories, minPrice, maxPrice, inStockOnly, sortBy } = options;

  let result = products.filter((p) => {
    if (query !== undefined && query !== null) {
      const q = String(query).trim().toLowerCase();
      if (q !== "") {
        const name = String(p.name ?? "").toLowerCase();
        const sku = String(p.sku ?? "").toLowerCase();
        if (!name.includes(q) && !sku.includes(q)) return false;
      }
    }
    if (categories && categories.length > 0 && !categories.includes(p.category)) {
      return false;
    }
    if (minPrice !== undefined && minPrice !== null && p.price < minPrice) return false;
    if (maxPrice !== undefined && maxPrice !== null && p.price > maxPrice) return false;
    if (inStockOnly && !(p.stock > 0)) return false;
    return true;
  });

  if (sortBy) {
    const compare =
      sortBy === "price-asc"
        ? (a, b) => a.price - b.price
        : sortBy === "price-desc"
        ? (a, b) => b.price - a.price
        : sortBy === "name-asc"
        ? (a, b) => String(a.name).localeCompare(String(b.name))
        : null;
    if (compare) result = result.slice().sort(compare);
  }

  return result;
}
