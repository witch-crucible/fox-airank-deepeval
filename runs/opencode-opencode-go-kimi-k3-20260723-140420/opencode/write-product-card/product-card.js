function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function renderProductCard(product) {
  const { sku, imageUrl, name, price, description, stock } = product;
  const inStock = stock > 0;
  const button = inStock
    ? '<button type="button" data-action="add-to-cart">加入购物车</button>'
    : '<button type="button" disabled>暂时缺货</button>';
  return `<article class="product-card" data-sku="${escapeHtml(sku)}">
  <img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(name)}">
  <h2>${escapeHtml(name)}</h2>
  <p class="price">¥${price}</p>
  <p>${escapeHtml(description)}</p>
  ${button}
</article>`;
}
