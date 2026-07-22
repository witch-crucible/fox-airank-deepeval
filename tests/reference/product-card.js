function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

export function renderProductCard(product) {
  const available = product.stock > 0;
  const button = available
    ? '<button data-action="add-to-cart">加入购物车</button>'
    : '<button disabled>暂时缺货</button>';
  return `<article class="product-card" data-sku="${escapeHtml(product.sku)}"><img src="${escapeHtml(product.imageUrl)}" alt="${escapeHtml(product.name)}"><h2>${escapeHtml(product.name)}</h2><span>¥${Math.trunc(product.price)}</span><p>${escapeHtml(product.description)}</p>${button}</article>`;
}
