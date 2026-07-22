export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  const subtotal = items.reduce((sum, item) => {
    const price = Math.trunc(item.price);
    const quantity = Math.trunc(item.quantity);
    return quantity > 0 ? sum + price * quantity : sum;
  }, 0);
  const percent = coupon ? Math.min(100, Math.max(0, coupon.percent)) : 0;
  const discount = Math.round(subtotal * percent / 100);
  const afterDiscount = subtotal - discount;
  const shipping = afterDiscount >= shippingThreshold ? 0 : shippingFee;
  return { subtotal, discount, shipping, total: Math.max(0, afterDiscount + shipping) };
}
