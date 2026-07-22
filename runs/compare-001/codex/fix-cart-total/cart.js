export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  const subtotal = items.reduce((sum, item) => {
    const price = Math.trunc(Number(item.price));
    const quantity = Math.trunc(Number(item.quantity));

    if (!Number.isFinite(quantity) || quantity <= 0) {
      return sum;
    }

    return sum + (Number.isFinite(price) ? price : 0) * quantity;
  }, 0);
  const couponPercent = Number(coupon?.percent);
  const percent = Number.isFinite(couponPercent)
    ? Math.min(100, Math.max(0, couponPercent))
    : 0;
  const discount = percent === 0 ? 0 : Math.round(subtotal * percent / 100);
  const discountedSubtotal = subtotal - discount;
  const shipping = discountedSubtotal >= shippingThreshold ? 0 : shippingFee;
  const total = Math.max(0, discountedSubtotal + shipping);

  return { subtotal, discount, shipping, total };
}
