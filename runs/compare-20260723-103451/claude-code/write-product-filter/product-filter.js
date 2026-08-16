export function filterProducts(products, options = {}) {
  const { query, categories, minPrice, maxPrice, inStockOnly, sortBy } = options;

  const normalizedQuery = typeof query === "string" ? query.trim().toLowerCase() : "";

  const filtered = products.filter((product) => {
    if (normalizedQuery) {
      const name = String(product.name).toLowerCase();
      const sku = String(product.sku).toLowerCase();
      if (!name.includes(normalizedQuery) && !sku.includes(normalizedQuery)) {
        return false;
      }
    }

    if (Array.isArray(categories) && categories.length > 0) {
      if (!categories.includes(product.category)) {
        return false;
      }
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

  const indexed = filtered.map((product, index) => ({ product, index }));

  let comparator = null;
  if (sortBy === "price-asc") {
    comparator = (a, b) => a.product.price - b.product.price;
  } else if (sortBy === "price-desc") {
    comparator = (a, b) => b.product.price - a.product.price;
  } else if (sortBy === "name-asc") {
    comparator = (a, b) => (a.product.name < b.product.name ? -1 : a.product.name > b.product.name ? 1 : 0);
  }

  if (comparator) {
    indexed.sort((a, b) => comparator(a, b) || a.index - b.index);
  }

  return indexed.map((entry) => entry.product);
}
