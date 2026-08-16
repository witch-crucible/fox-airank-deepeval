export function filterProducts(products, options = {}) {
  const { query, categories, minPrice, maxPrice, inStockOnly, sortBy } = options;

  const normalizedQuery =
    typeof query === "string" ? query.trim().toLowerCase() : "";
  const categoryList = Array.isArray(categories) ? categories : [];

  const filtered = products.filter((product) => {
    if (normalizedQuery) {
      const name = String(product.name ?? "").toLowerCase();
      const sku = String(product.sku ?? "").toLowerCase();
      if (!name.includes(normalizedQuery) && !sku.includes(normalizedQuery)) {
        return false;
      }
    }
    if (categoryList.length > 0 && !categoryList.includes(product.category)) {
      return false;
    }
    if (minPrice != null && product.price < minPrice) {
      return false;
    }
    if (maxPrice != null && product.price > maxPrice) {
      return false;
    }
    if (inStockOnly && !(product.stock > 0)) {
      return false;
    }
    return true;
  });

  const comparators = {
    "price-asc": (a, b) => a.price - b.price,
    "price-desc": (a, b) => b.price - a.price,
    "name-asc": (a, b) => String(a.name).localeCompare(String(b.name))
  };
  const comparator = comparators[sortBy];
  if (comparator) {
    filtered.sort(comparator);
  }

  return filtered;
}
