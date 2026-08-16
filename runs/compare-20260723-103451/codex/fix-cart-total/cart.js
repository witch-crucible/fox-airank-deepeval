export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  const subtotal = items.reduce((sum, item) => {
    const price = Math.trunc(item.price);
    const quantity = Math.trunc(item.quantity);
    return quantity > 0 ? sum + price * quantity : sum;
  }, 0);
  const percent = coupon
    ? Math.min(100, Math.max(0, coupon.percent))
    : 0;
  const discount = Math.round(subtotal * percent / 100);
  const discountedSubtotal = subtotal - discount;
  const shipping = discountedSubtotal >= shippingThreshold ? 0 : shippingFee;
  const total = Math.max(0, discountedSubtotal + shipping);
  return { subtotal, discount, shipping, total };
}
