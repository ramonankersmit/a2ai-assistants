export function getByPointer(obj, pointer) {
  if (!pointer || pointer === '/') return obj;
  const parts = pointer.split('/').filter(Boolean);
  let cur = obj;
  for (const p of parts) {
    if (cur == null) return undefined;
    cur = cur[p];
  }
  return cur;
}

function ensurePath(obj, pointer) {
  const parts = pointer.split('/').filter(Boolean);
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const seg = parts[i];
    if (typeof cur[seg] !== 'object' || cur[seg] === null || Array.isArray(cur[seg])) {
      cur[seg] = {};
    }
    cur = cur[seg];
  }
  return { parent: cur, key: parts[parts.length - 1] };
}

export function applyPatches(model, patches) {
  for (const p of patches) {
    const op = p.op;
    const path = p.path;
    const value = p.value;
    if (!path || typeof path !== 'string' || !path.startsWith('/')) continue;
    if (op !== 'add' && op !== 'replace') continue;
    const { parent, key } = ensurePath(model, path);
    if (key === undefined) continue;
    parent[key] = value;
  }
  return model;
}
