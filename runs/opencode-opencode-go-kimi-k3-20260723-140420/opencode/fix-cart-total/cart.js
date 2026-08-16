export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  const subtotal = items.reduce((sum, item) => {
    const price = Math.trunc(item.price);
    const quantity = Math.trunc(item.quantity);
    if (quantity <= 0) return sum;
    return sum + price * quantity;
  }, 0);
  const percent = coupon ? Math.min(Math.max(Math.trunc(coupon.percent), 0), 100) : 0;
  const discount = Math.round((subtotal * percent) / 100);
  const discounted = subtotal - discount;
  const shipping = discounted >= shippingThreshold ? 0 : shippingFee;
  const total = Math.max(discounted + shipping, 0);
  return { subtotal, discount, shipping, total };
}
