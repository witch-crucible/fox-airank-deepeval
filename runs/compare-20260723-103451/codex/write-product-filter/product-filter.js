export function filterProducts(products, options = {}) {
  const {
    query,
    categories,
    minPrice,
    maxPrice,
    inStockOnly,
    sortBy
  } = options;
  const normalizedQuery =
    query === undefined ? "" : String(query).trim().toLowerCase();
  const selectedCategories =
    Array.isArray(categories) && categories.length > 0 ? categories : null;

  const filtered = products.filter((product) => {
    if (
      normalizedQuery &&
      !String(product.name).toLowerCase().includes(normalizedQuery) &&
      !String(product.sku).toLowerCase().includes(normalizedQuery)
    ) {
      return false;
    }
    if (selectedCategories && !selectedCategories.includes(product.category)) {
      return false;
    }
    if (minPrice !== undefined && product.price < minPrice) {
      return false;
    }
    if (maxPrice !== undefined && product.price > maxPrice) {
      return false;
    }
    if (inStockOnly && product.stock <= 0) {
      return false;
    }
    return true;
  });

  const comparators = {
    "price-asc": (left, right) => left.price - right.price,
    "price-desc": (left, right) => right.price - left.price,
    "name-asc": (left, right) => left.name.localeCompare(right.name)
  };
  const compare = comparators[sortBy];

  if (!compare) {
    return filtered;
  }

  return filtered
    .map((product, index) => ({ product, index }))
    .sort((left, right) => {
      const order = compare(left.product, right.product);
      return order === 0 ? left.index - right.index : order;
    })
    .map(({ product }) => product);
}
