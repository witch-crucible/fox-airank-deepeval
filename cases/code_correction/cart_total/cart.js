export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  if (!Array.isArray(items)) throw new TypeError("items must be an array");
  const subtotal = items.reduce((sum, item) => {
    const price = Number(item?.price);
    const quantity = Number(item?.quantity ?? 1);
    if (!Number.isFinite(price) || !Number.isFinite(quantity) || quantity <= 0) return sum;
    return sum + Math.trunc(price) * Math.trunc(quantity);
  }, 0);
  const percent = coupon ? Math.min(1, Math.max(0, Number(coupon.percent) || 0)) : 0;
  const discount = Math.round(subtotal * percent);
  const afterDiscount = subtotal - discount;
  const shipping = afterDiscount >= Number(shippingThreshold) ? 0 : Number(shippingFee) || 0;
  return { subtotal, discount, shipping, total: Math.max(0, afterDiscount + shipping) };
}
