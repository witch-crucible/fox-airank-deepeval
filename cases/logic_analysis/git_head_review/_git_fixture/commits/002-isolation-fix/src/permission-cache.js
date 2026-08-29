const permissionCache = new Map();

function cacheKey({ tenantId, userId, documentId }) {
  return `${tenantId}:${userId}:${documentId}`;
}

export function getPermission(context, evaluate) {
  const key = cacheKey(context);
  if (!permissionCache.has(key)) {
    permissionCache.set(key, evaluate(context));
  }
  return permissionCache.get(key);
}

export function clearPermissionCache() {
  permissionCache.clear();
}
