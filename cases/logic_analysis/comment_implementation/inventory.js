/**
 * 是否允许加入购物车。
 * stock === null 表示该渠道不限制库存，应允许购买。
 * stock === 0 表示已售罄，应禁止购买。
 * stock > 0 表示可售，应允许购买。
 */
export function canAddToCart(stock) {
  if (stock === null || stock === undefined) return true;
  if (stock === 0) return false;
  return stock > 0;
}
