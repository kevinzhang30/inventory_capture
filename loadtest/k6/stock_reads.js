// Stock reads: 80% hot keys (top HOT skus), 20% uniform. NFR: cache-hit p99 < 20 ms server-side
// (measure server-side in CloudWatch; k6 reports client-observed latency including network).
import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';
import { API, headers, PARTS } from './common.js';

const HOT = parseInt(__ENV.HOT || '50', 10);
const cacheHit = new Trend('stock_cache_hit_ms', true);

export const options = {
  scenarios: {
    reads: { executor: 'constant-arrival-rate', rate: parseInt(__ENV.RPS || '1000', 10), timeUnit: '1s',
             duration: __ENV.DURATION || '5m', preAllocatedVUs: 100, maxVUs: 500 },
  },
  thresholds: {
    stock_cache_hit_ms: ['p(99)<50'],
    http_req_failed: ['rate<0.001'],
  },
};

export default function () {
  const n = Math.random() < 0.8 ? 1 + Math.floor(Math.random() * HOT) : 1 + Math.floor(Math.random() * PARTS);
  const sku = `SKU-${String(n).padStart(6, '0')}`;
  const res = http.get(`${API}/stock/${sku}`, { headers: headers(), tags: { name: 'stock' } });
  check(res, { '200': (r) => r.status === 200 });
  if (res.status === 200 && res.json('source') === 'cache') cacheHit.add(res.timings.duration);
}
