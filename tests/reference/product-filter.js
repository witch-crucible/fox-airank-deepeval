export function filterProducts(products, options = {}) {
  const query = (options.query ?? "").trim().toLowerCase();
  const categories = options.categories ?? [];
  const values = products.filter((product) => {
    const matchesQuery = !query || product.name.toLowerCase().includes(query) || product.sku.toLowerCase().includes(query);
    const matchesCategory = categories.length === 0 || categories.includes(product.category);
    const matchesMin = options.minPrice === undefined || product.price >= options.minPrice;
    const matchesMax = options.maxPrice === undefined || product.price <= options.maxPrice;
    const matchesStock = !options.inStockOnly || product.stock > 0;
    return matchesQuery && matchesCategory && matchesMin && matchesMax && matchesStock;
  }).map((product, index) => ({ product, index }));
  const comparators = {
    "price-asc": (a, b) => a.product.price - b.product.price,
    "price-desc": (a, b) => b.product.price - a.product.price,
    "name-asc": (a, b) => a.product.name.localeCompare(b.product.name),
  };
  const compare = comparators[options.sortBy];
  if (compare) values.sort((a, b) => compare(a, b) || a.index - b.index);
  return values.map(({ product }) => product);
}
