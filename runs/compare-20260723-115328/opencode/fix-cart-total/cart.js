export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  const validItems = items.filter(item => item.quantity > 0);
  const subtotal = validItems.reduce((sum, item) => sum + item.price * item.quantity, 0);
  
  let discount = 0;
  if (coupon && typeof coupon.percent === 'number') {
    const percent = Math.max(0, Math.min(100, coupon.percent));
    discount = Math.round(subtotal * percent / 100);
  }
  
  const afterDiscount = subtotal - discount;
  const shipping = afterDiscount >= shippingThreshold ? 0 : shippingFee;
  const total = Math.max(0, afterDiscount + shipping);
  
  return { subtotal, discount, shipping, total };
}
