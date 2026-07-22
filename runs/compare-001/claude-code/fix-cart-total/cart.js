export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  const subtotal = items.reduce((sum, item) => sum + item.price, 0);
  const discount = coupon ? subtotal * coupon.percent : 0;
  const shipping = subtotal > shippingThreshold ? 0 : shippingFee;
  return { subtotal, discount, shipping, total: subtotal - discount + shipping };
}
