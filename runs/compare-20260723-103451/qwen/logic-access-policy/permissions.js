export function canView(role, orderStatus) {
  if (role === "admin") return true;
  if (orderStatus === "archived") return false;
  return role === "editor" || role === "reviewer";
}

export function canEdit(role, orderStatus) {
  if (role === "admin") return true;
  if (orderStatus === "draft") return role === "editor";
  if (orderStatus === "submitted") return role === "editor" || role === "reviewer";
  return false;
}
