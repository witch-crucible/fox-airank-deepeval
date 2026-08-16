export function filterProducts(products, options = {}) {
  const { query, categories, minPrice, maxPrice, inStockOnly, sortBy } = options;

  // Create a new array with copied objects to avoid mutation
  let filtered = products.map(p => ({ ...p }));

  // Filter by query (trim whitespace, case-insensitive, match name OR sku)
  if (query !== undefined) {
    const trimmedQuery = query.trim().toLowerCase();
    if (trimmedQuery !== "") {
      filtered = filtered.filter(p =>
        p.name.toLowerCase().includes(trimmedQuery) ||
        p.sku.toLowerCase().includes(trimmedQuery)
      );
    }
  }

  // Filter by categories (exact match, case-sensitive)
  if (categories !== undefined && Array.isArray(categories) && categories.length > 0) {
    filtered = filtered.filter(p => categories.includes(p.category));
  }

  // Filter by minPrice (inclusive)
  if (minPrice !== undefined) {
    filtered = filtered.filter(p => p.price >= minPrice);
  }

  // Filter by maxPrice (inclusive)
  if (maxPrice !== undefined) {
    filtered = filtered.filter(p => p.price <= maxPrice);
  }

  // Filter by inStockOnly
  if (inStockOnly) {
    filtered = filtered.filter(p => p.stock > 0);
  }

  // Sort
  if (sortBy === "price-asc") {
    filtered.sort((a, b) => a.price - b.price);
  } else if (sortBy === "price-desc") {
    filtered.sort((a, b) => b.price - a.price);
  } else if (sortBy === "name-asc") {
    filtered.sort((a, b) => a.name.localeCompare(b.name));
  }
  // If no sortBy or unknown value, keep original order (stable sort maintains original order for equal values)

  return filtered;
}