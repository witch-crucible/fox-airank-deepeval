export function filterProducts(products, options = {}) {
  const query = String(options.query ?? "").trim().toLowerCase();
  const categories = Array.isArray(options.categories) ? options.categories : [];
  return products.filter(product => {
    const textMatch = !query || [product.name, product.sku].some(value => String(value ?? "").toLowerCase().includes(query));
    const categoryMatch = !categories.length || categories.includes(product.category);
    const minMatch = options.minPrice == null || product.price >= options.minPrice;
    const maxMatch = options.maxPrice == null || product.price <= options.maxPrice;
    const stockMatch = !options.inStockOnly || product.stock > 0;
    return textMatch && categoryMatch && minMatch && maxMatch && stockMatch;
  }).map((product, index, source) => ({ product, index })).sort((a, b) => {
    const key = options.sortBy;
    if (!key) return a.index - b.index;
    const result = key === "price-asc" ? a.product.price - b.product.price : key === "price-desc" ? b.product.price - a.product.price : key === "name-asc" ? String(a.product.name).localeCompare(String(b.product.name)) : 0;
    return result || a.index - b.index;
  }).map(entry => entry.product);
}
