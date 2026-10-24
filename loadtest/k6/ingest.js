// Sustained ingest: CAPTURES_PER_S captures/s (default 2000) as batches of BATCH (default 25) for DURATION.
// NFR: POST /captures p99 < 150 ms, no failed requests, no rejected items.
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { API, headers, randomLocation, randomSku, SITE, uuid7 } from './common.js';

const RATE = parseInt(__ENV.CAPTURES_PER_S || '2000', 10);
const BATCH = parseInt(__ENV.BATCH || '25', 10);
const rejected = new Counter('captures_rejected');
const accepted = new Counter('captures_accepted');

export const options = {
  scenarios: {
    ingest: {
      executor: 'constant-arrival-rate',
      rate: Math.ceil(RATE / BATCH),
      timeUnit: '1s',
      duration: __ENV.DURATION || '10m',
      preAllocatedVUs: 100,
      maxVUs: 1000,
    },
  },
  thresholds: {
    'http_req_duration{name:captures}': ['p(99)<150'],
    http_req_failed: ['rate<0.001'],
    captures_rejected: ['count<1'],
  },
};

export default function () {
  const station = `${SITE}-K6-${String(__VU % 200).padStart(3, '0')}`;
  const captures = [];
  for (let i = 0; i < BATCH; i++) {
    captures.push({
      capture_id: uuid7(),
      site_id: SITE,
      station_id: station,
      kind: 'scan',
      captured_at: new Date().toISOString(),
      payload: { sku: randomSku(), qty: 1 + Math.floor(Math.random() * 10), location_id: randomLocation() },
    });
  }
  const res = http.post(`${API}/captures`, JSON.stringify({ captures }), {
    headers: headers('operator'),
    tags: { name: 'captures' },
  });
  check(res, { '202': (r) => r.status === 202 });
  if (res.status === 202) {
    for (const item of res.json('results')) {
      if (item.status === 'rejected') rejected.add(1);
      else accepted.add(1);
    }
  }
}
