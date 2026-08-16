export function filterProducts(products, options = {}) {
  const { query, categories, minPrice, maxPrice, inStockOnly, sortBy } = options;

  const normalizedQuery =
    typeof query === "string" ? query.trim().toLowerCase() : "";
  const hasCategories = Array.isArray(categories) && categories.length > 0;
  const categorySet = hasCategories ? new Set(categories) : null;

  let result = products.filter((product) => {
    if (normalizedQuery) {
      const name = String(product.name ?? "").toLowerCase();
      const sku = String(product.sku ?? "").toLowerCase();
      if (!name.includes(normalizedQuery) && !sku.includes(normalizedQuery)) {
        return false;
      }
    }

    if (categorySet && !categorySet.has(product.category)) {
      return false;
    }

    if (typeof minPrice === "number" && product.price < minPrice) {
      return false;
    }

    if (typeof maxPrice === "number" && product.price > maxPrice) {
      return false;
    }

    if (inStockOnly && !(product.stock > 0)) {
      return false;
    }

    return true;
  });

  if (sortBy === "price-asc") {
    result.sort((a, b) => a.price - b.price);
  } else if (sortBy === "price-desc") {
    result.sort((a, b) => b.price - a.price);
  } else if (sortBy === "name-asc") {
    result.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  }

  return result;
}
