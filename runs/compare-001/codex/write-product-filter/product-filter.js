export function filterProducts(products, options = {}) {
  const {
    query,
    categories,
    minPrice,
    maxPrice,
    inStockOnly,
    sortBy
  } = options;
  const normalizedQuery = query?.trim().toLowerCase();
  const categoryFilter = Array.isArray(categories) && categories.length > 0;

  const filteredProducts = products.filter((product) => {
    if (
      normalizedQuery &&
      !product.name.toLowerCase().includes(normalizedQuery) &&
      !product.sku.toLowerCase().includes(normalizedQuery)
    ) {
      return false;
    }

    if (categoryFilter && !categories.includes(product.category)) {
      return false;
    }

    if (minPrice !== undefined && product.price < minPrice) {
      return false;
    }

    if (maxPrice !== undefined && product.price > maxPrice) {
      return false;
    }

    return !inStockOnly || product.stock > 0;
  });

  const comparators = {
    "price-asc": (left, right) => left.price - right.price,
    "price-desc": (left, right) => right.price - left.price,
    "name-asc": (left, right) => left.name.localeCompare(right.name)
  };
  const comparator = comparators[sortBy];

  if (!comparator) {
    return filteredProducts;
  }

  return filteredProducts
    .map((product, index) => ({ product, index }))
    .sort((left, right) =>
      comparator(left.product, right.product) || left.index - right.index
    )
    .map(({ product }) => product);
}
