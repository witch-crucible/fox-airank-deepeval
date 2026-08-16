function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function renderProductCard(product) {
  const sku = escapeHtml(product.sku);
  const imageUrl = escapeHtml(product.imageUrl);
  const name = escapeHtml(product.name);
  const description = escapeHtml(product.description);
  const price = Math.trunc(product.price);
  const inStock = product.stock > 0;

  const button = inStock
    ? `<button data-action="add-to-cart">加入购物车</button>`
    : `<button disabled>暂时缺货</button>`;

  return (
    `<article class="product-card" data-sku="${sku}">` +
    `<img src="${imageUrl}" alt="${name}">` +
    `<h2>${name}</h2>` +
    `<p class="price">¥${price}</p>` +
    `<p>${description}</p>` +
    button +
    `</article>`
  );
}
