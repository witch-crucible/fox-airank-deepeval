export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  const subtotal = items.reduce((sum, item) => {
    const price = Math.trunc(item.price);
    const quantity = Math.trunc(item.quantity);
    return quantity > 0 ? sum + price * quantity : sum;
  }, 0);

  const percent = coupon ? Math.max(0, Math.min(100, coupon.percent)) : 0;
  const discount = coupon ? Math.round((subtotal * percent) / 100) : 0;

  const discountedSubtotal = subtotal - discount;
  const shipping = discountedSubtotal >= shippingThreshold ? 0 : shippingFee;
  const total = Math.max(0, discountedSubtotal + shipping);

  return { subtotal, discount, shipping, total };
}
