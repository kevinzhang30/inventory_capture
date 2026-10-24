// Search: realistic fuzzy queries with facets. NFR: p95 < 150 ms.
import http from 'k6/http';
import { check } from 'k6';
import { API, headers } from './common.js';

const QUERIES = ['hex bolt', 'bearing', 'ACME', 'relay', 'o-ring', 'M8', 'timing belt', 'SKU-0001', 'gaer',
  'contactr', 'washer', 'BOLT-4', 'coupler', 'carton', 'fuse 10mm'];
const CATEGORIES = ['fasteners', 'bearings', 'electrical', 'hydraulics', 'packaging', 'motion'];

export const options = {
  scenarios: {
    search: { executor: 'constant-arrival-rate', rate: parseInt(__ENV.RPS || '200', 10), timeUnit: '1s',
              duration: __ENV.DURATION || '5m', preAllocatedVUs: 50, maxVUs: 300 },
  },
  thresholds: { 'http_req_duration{name:search}': ['p(95)<150'], http_req_failed: ['rate<0.001'] },
};

export default function () {
  let url = `${API}/search/parts?q=${encodeURIComponent(QUERIES[Math.floor(Math.random() * QUERIES.length)])}`;
  if (Math.random() < 0.3) url += `&category=${CATEGORIES[Math.floor(Math.random() * CATEGORIES.length)]}`;
  if (Math.random() < 0.2) url += '&site=DAL1';
  const res = http.get(url, { headers: headers(), tags: { name: 'search' } });
  check(res, { '200': (r) => r.status === 200 });
}
