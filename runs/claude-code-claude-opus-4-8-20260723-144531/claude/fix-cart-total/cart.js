export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  const subtotal = items.reduce((sum, item) => {
    const quantity = Math.trunc(item.quantity);
    if (quantity <= 0) return sum;
    return sum + Math.trunc(item.price) * quantity;
  }, 0);
  const percent = coupon ? Math.min(100, Math.max(0, coupon.percent)) : 0;
  const discount = Math.round((subtotal * percent) / 100);
  const discounted = subtotal - discount;
  const shipping = discounted >= shippingThreshold ? 0 : shippingFee;
  return { subtotal, discount, shipping, total: Math.max(0, discounted + shipping) };
}
