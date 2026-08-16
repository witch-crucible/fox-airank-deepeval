function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function renderProductCard(product) {
  const { sku, imageUrl, name, description, price, stock } = product;

  const safeSku = escapeHtml(sku);
  const safeImageUrl = escapeHtml(imageUrl);
  const safeName = escapeHtml(name);
  const safeDescription = escapeHtml(description);

  const button = stock
    ? `<button data-action="add-to-cart">加入购物车</button>`
    : `<button disabled>暂时缺货</button>`;

  return `<article class="product-card" data-sku="${safeSku}">
  <img src="${safeImageUrl}" alt="${safeName}">
  <h2>${safeName}</h2>
  <p class="price">¥${Math.trunc(price)}</p>
  <p>${safeDescription}</p>
  ${button}
</article>`;
}
