/**
 * k6 load test — InfinitePay Agent Swarm
 *
 * Usage:
 *   # local (uvicorn on :8000)
 *   BASE_URL=http://localhost:8000 \
 *   LOGIN_EMAIL=carlos.andrade@infinitepay.test \
 *   LOGIN_PASSWORD=Test123! \
 *   k6 run scripts/load_test.k6.js
 *
 *   # against Railway
 *   BASE_URL=https://cloudwalk-agent-swarm-challenge.up.railway.app \
 *   LOGIN_EMAIL=... LOGIN_PASSWORD=... \
 *   k6 run scripts/load_test.k6.js
 *
 * What it measures:
 *   - /chat end-to-end latency (agent call + RAG hit)
 *   - /health latency (should be trivially fast)
 *   - error rate under concurrent load
 *
 * The scenario ramps to 10 concurrent VUs over 1 minute, holds for 2 min,
 * ramps down. Anthropic rate limits dominate anything above this — crank
 * the targets only if you've raised your Claude RPM quota.
 *
 * SLAs (thresholds block the run from passing):
 *   - chat P95 < 12s  (Anthropic typical P95 is ~6s; +6s headroom for RAG + graph)
 *   - chat P99 < 25s
 *   - health P95 < 500ms
 *   - overall HTTP error rate < 2%
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const LOGIN_EMAIL = __ENV.LOGIN_EMAIL || 'carlos.andrade@infinitepay.test';
const LOGIN_PASSWORD = __ENV.LOGIN_PASSWORD || 'Test123!';

const chatLatency = new Trend('chat_latency_ms', true);
const healthLatency = new Trend('health_latency_ms', true);
const chatErrors = new Rate('chat_errors');

export const options = {
  scenarios: {
    soak: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: 10 },
        { duration: '2m', target: 10 },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    chat_latency_ms: ['p(95)<12000', 'p(99)<25000'],
    health_latency_ms: ['p(95)<500'],
    chat_errors: ['rate<0.02'],
    http_req_failed: ['rate<0.05'],
  },
};

const QUESTIONS = [
  'What are the fees for the Maquininha Smart?',
  'Quais as taxas da Maquininha Smart?',
  'How do I accept payments on my phone without a card reader?',
  'Como usar meu celular como maquininha?',
  'What is the InfinitePay digital account?',
  'Quanto custa a conta digital InfinitePay?',
];

function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

export function setup() {
  const res = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({ email: LOGIN_EMAIL, password: LOGIN_PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  if (res.status !== 200) {
    throw new Error(`login failed: ${res.status} ${res.body}`);
  }
  const token = res.json('access_token');
  if (!token) throw new Error('login response missing access_token');
  return { token };
}

export default function (data) {
  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${data.token}`,
  };

  group('health', () => {
    const res = http.get(`${BASE_URL}/health`);
    healthLatency.add(res.timings.duration);
    check(res, { 'health 200': (r) => r.status === 200 });
  });

  group('chat', () => {
    const body = JSON.stringify({ message: pick(QUESTIONS) });
    const res = http.post(`${BASE_URL}/chat`, body, { headers, timeout: '60s' });
    chatLatency.add(res.timings.duration);
    const ok = check(res, {
      'chat 200': (r) => r.status === 200,
      'chat body has response': (r) => {
        try { return typeof r.json('response') === 'string'; } catch (_) { return false; }
      },
    });
    chatErrors.add(!ok);
  });

  sleep(Math.random() * 2 + 1); // 1–3s think time
}
