export function renderProductCard(product) {
  const { sku, imageUrl, name, price, description, stock } = product;

  const escape = (str) => {
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return String(str).replace(/[&<>"']/g, (ch) => map[ch]);
  };

  const safeSku = escape(sku);
  const safeImageUrl = escape(imageUrl);
  const safeName = escape(name);
  const safeDesc = escape(description);
  const displayPrice = `\u00a5${Math.floor(price)}`;

  const inStock = stock > 0;
  const buttonText = inStock ? "\u52a0\u5165\u8d2d\u7269\u8f66" : "\u6682\u65f6\u7f3a\u8d27";
  const extra = inStock ? ' data-action="add-to-cart"' : ' disabled';

  return `<article class="product-card" data-sku="${safeSku}">\n  <img src="${safeImageUrl}" alt="${safeName}">\n  <h2>${safeName}</h2>\n  <p>${displayPrice}</p>\n  <p>${safeDesc}</p>\n  <button${extra}>${buttonText}</button>\n</article>`;
}
