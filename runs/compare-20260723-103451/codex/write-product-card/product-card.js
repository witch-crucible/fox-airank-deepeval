function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderProductCard(product) {
  const sku = escapeHtml(product.sku);
  const imageUrl = escapeHtml(product.imageUrl);
  const name = escapeHtml(product.name);
  const description = escapeHtml(product.description);
  const price = Math.trunc(Number(product.price));
  const button = product.stock > 0
    ? '<button type="button" data-action="add-to-cart">加入购物车</button>'
    : '<button type="button" disabled>暂时缺货</button>';

  return `<article class="product-card" data-sku="${sku}">
  <img src="${imageUrl}" alt="${name}">
  <h2>${name}</h2>
  <p class="price">¥${price}</p>
  <p>${description}</p>
  ${button}
</article>`;
}
