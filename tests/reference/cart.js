export function calculateCart(items, coupon, shippingThreshold, shippingFee) {
  if (!Array.isArray(items)) throw new TypeError("items must be an array");
  const subtotal = items.reduce((sum, item) => {
    const price = Number(item?.price);
    const quantity = Number(item?.quantity ?? 1);
    return Number.isFinite(price) && Number.isFinite(quantity) && quantity > 0
      ? sum + Math.trunc(price) * Math.trunc(quantity) : sum;
  }, 0);
  const percent = coupon ? Math.min(100, Math.max(0, Number(coupon.percent) || 0)) : 0;
  const discount = Math.round(subtotal * percent / 100);
  const afterDiscount = subtotal - discount;
  const shipping = afterDiscount >= Number(shippingThreshold) ? 0 : Number(shippingFee) || 0;
  return { subtotal, discount, shipping, total: Math.max(0, afterDiscount + shipping) };
}
