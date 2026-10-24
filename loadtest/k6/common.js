// Shared k6 config: K6_API (base URL), K6_AUTH_MODE (dev|bearer), K6_TOKEN (Cognito id token for bearer).
export const API = __ENV.K6_API || 'http://localhost:8080';
const MODE = __ENV.K6_AUTH_MODE || 'dev';

export function headers(groups = 'operator,reviewer') {
  const h = { 'content-type': 'application/json' };
  if (MODE === 'bearer') {
    h.authorization = `Bearer ${__ENV.K6_TOKEN}`;
  } else {
    h['x-dev-user'] = 'k6';
    h['x-dev-groups'] = groups;
  }
  return h;
}

const HEX = '0123456789abcdef';
function hex(n) {
  let s = '';
  for (let i = 0; i < n; i++) s += HEX[Math.floor(Math.random() * 16)];
  return s;
}

// UUIDv7: 48-bit ms timestamp, version 7, variant 10, random rest.
export function uuid7() {
  const ts = Date.now().toString(16).padStart(12, '0');
  const variant = HEX[8 + Math.floor(Math.random() * 4)];
  return `${ts.slice(0, 8)}-${ts.slice(8, 12)}-7${hex(3)}-${variant}${hex(3)}-${hex(12)}`;
}

export const PARTS = parseInt(__ENV.K6_PARTS || '2000', 10);
export const SITE = __ENV.K6_SITE || 'DAL1';

export function randomSku() {
  return `SKU-${String(1 + Math.floor(Math.random() * PARTS)).padStart(6, '0')}`;
}

export function randomLocation() {
  const aisle = 'ABCD'[Math.floor(Math.random() * 4)];
  const bay = String(1 + Math.floor(Math.random() * 5)).padStart(2, '0');
  return `${SITE}-${aisle}${bay}-01`;
}
