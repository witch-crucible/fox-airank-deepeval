function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };

    return entities[character];
  });
}

export function renderProductCard(product) {
  const sku = escapeHtml(product.sku);
  const imageUrl = escapeHtml(product.imageUrl);
  const name = escapeHtml(product.name);
  const description = escapeHtml(product.description);
  const button = product.stock > 0
    ? '<button type="button" data-action="add-to-cart">加入购物车</button>'
    : '<button type="button" disabled>暂时缺货</button>';

  return `<article class="product-card" data-sku="${sku}">
  <img src="${imageUrl}" alt="${name}">
  <h2>${name}</h2>
  <p class="price">¥${product.price}</p>
  <p>${description}</p>
  ${button}
</article>`;
}
