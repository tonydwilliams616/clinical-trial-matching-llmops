// Load test for the PII gateway's /v1/assess: masking + leftover check +
// Bedrock, at a rising request rate. Run inside the cluster as a Job
// (see ../README.md). Synthetic notes only, with planted fake identifiers
// (555-01xx phones, example.com emails, made-up MRNs) so masking does real work.
//
// Pass/fail mirrors the SLOs in gitops/platform/monitoring/slo-rules.yaml:
//   - 95% of answered requests within 5 s
//   - under 1% server errors (5xx)
// A 422 (the safety check refusing a note) is an expected outcome, not an error.

import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate } from 'k6/metrics';

const GATEWAY = __ENV.GATEWAY_URL || 'http://pii-gateway.pii-gateway';

const serverErrors = new Rate('server_errors');
const refusals = new Counter('refusals');
const throttled = new Counter('model_unavailable_502');

http.setResponseCallback(http.expectedStatuses(200, 422));

// Two profiles, picked with PROFILE:
//   ramp (default) - 0 -> 1 -> 3 requests/s over 9 minutes: SLOs, throttling, HPA
//   soak           - a light constant rate for a long time (SOAK_RATE_PER_MIN,
//                    default 12; SOAK_MINUTES, default 90): a steady signal
//                    through a cluster upgrade, so any failed request shows up
const PROFILE = __ENV.PROFILE || 'ramp';
const PROFILES = {
  ramp: {
    // Requests per second, independent of how slow responses get: shows
    // where latency bends and where Bedrock starts throttling (502s)
    executor: 'ramping-arrival-rate',
    startRate: 0,
    timeUnit: '1s',
    preAllocatedVUs: 20,
    maxVUs: 60,
    stages: [
      { target: 1, duration: '1m' },  // warm up
      { target: 1, duration: '2m' },  // steady, light
      { target: 3, duration: '2m' },  // ramp
      { target: 3, duration: '3m' },  // steady, heavier
      { target: 0, duration: '1m' },  // ramp down
    ],
  },
  soak: {
    executor: 'constant-arrival-rate',
    rate: Number(__ENV.SOAK_RATE_PER_MIN || 12),
    timeUnit: '1m',
    duration: `${Number(__ENV.SOAK_MINUTES || 90)}m`,
    preAllocatedVUs: 5,
    maxVUs: 20,
  },
};
if (!PROFILES[PROFILE]) {
  throw new Error(`Unknown PROFILE "${PROFILE}" - use ramp or soak`);
}

export const options = {
  scenarios: { [PROFILE]: PROFILES[PROFILE] },
  thresholds: {
    'http_req_duration{expected_response:true}': ['p(95)<5000'],
    server_errors: ['rate<0.01'],
    checks: ['rate>0.99'],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const FIRST = ['John', 'Maria', 'Wei', 'Aisha', 'Tom', 'Elena', 'Kofi', 'Priya'];
const LAST = ['Smith', 'Garcia', 'Chen', 'Okafor', 'Novak', 'Patel', 'Mensah', 'Rossi'];
const FINDINGS = [
  'HbA1c 8.1% three months ago, 7.9% today. On metformin 1000 mg twice daily.',
  'Type 2 diabetes for 6 years. BP 128/82, well controlled on lisinopril.',
  'BP 168/104 today, second elevated reading this month. No insulin.',
  'Started basal insulin last year. eGFR 52. Reports occasional hypoglycaemia.',
  'BMI 33. Interested in a diet programme. No history of cardiovascular events.',
  'HbA1c 6.8%. Diet-controlled. Mild neuropathy in both feet.',
];
const CRITERIA = [
  'HbA1c between 7.5% and 11%',
  'No history of uncontrolled hypertension',
  'Not currently using insulin',
  'Body mass index of 30 or more',
  'eGFR of 45 or above',
];

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

function note() {
  const n = Math.floor(Math.random() * 90) + 10;
  return `Patient: ${pick(FIRST)} ${pick(LAST)}    MRN ${4800000 + Math.floor(Math.random() * 99999)}\n` +
    `Contact: (617) 555-01${n}, email patient${n}@example.com.\n` +
    `${pick(FINDINGS)} ${pick(FINDINGS)}`;
}

export default function () {
  const res = http.post(`${GATEWAY}/v1/assess`,
    JSON.stringify({ note: note(), criterion: pick(CRITERIA) }),
    { headers: { 'content-type': 'application/json' }, timeout: '60s' });

  serverErrors.add(res.status >= 500 || res.status === 0);
  if (res.status === 422) refusals.add(1);
  if (res.status === 502) throttled.add(1);

  check(res, {
    'answered or safely refused': (r) => r.status === 200 || r.status === 422,
    'verdict is one of three': (r) => r.status !== 200 ||
      ['likely_meets', 'likely_fails', 'unclear'].includes(r.json('verdict')),
  });
}
