// ============================================================
// heavy_loop.js — Via l'API Gateway (port 8080)
// ============================================================

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { API_BASE_URL, TIMEOUT } from './config.js';

const errorsTotal  = new Counter('university_errors_total');
const latencyTrend = new Trend('university_latency_ms');

// 502/503 ne comptent pas comme des échecs pour http_req_failed
http.setResponseCallback(
  http.expectedStatuses({ min: 200, max: 399 }, 502, 503)
);

export const options = {
  vus:      1,
  duration: '24h',
  thresholds: {
    http_req_failed:   ['rate<0.10'],
    http_req_duration: ['p(95)<3000'],
  },
};

function randomHex(len) {
  const chars = '0123456789abcdef';
  let result = '';
  for (let i = 0; i < len; i++) {
    result += chars[Math.floor(Math.random() * chars.length)];
  }
  return result;
}

function traceHeaders() {
  return {
    'Content-Type': 'application/json',
    'traceparent':  `00-${randomHex(32)}-${randomHex(16)}-01`,
  };
}

// Erreur "tolérée" : le service est indisponible
function isUnavailable(res) {
  return res.status === 502 || res.status === 503;
}

export default function () {
  const studentIds        = [];  // IDs utilisés pour les inscriptions (réels + secours)
  const createdStudentIds = [];  // IDs réellement créés (pour le nettoyage)
  const courseIds         = [];
  const enrollmentIds     = [];

  // ────────────────────────────────────────────────────────
  // 1. Création de 20 étudiants (avec ID de secours si échec)
  // ────────────────────────────────────────────────────────
  for (let i = 1; i <= 20; i++) {
    const email = `student_${__VU}_${__ITER}_${i}_${Date.now()}@load.test`;
    let r = http.post(
      `${API_BASE_URL}/students/students`,
      JSON.stringify({
        first_name: `Etudiant${i}`,
        last_name:  `Test`,
        email:      email,
      }),
      { headers: traceHeaders(), timeout: TIMEOUT }
    );

    check(r, { 'POST /students 201': (res) => res.status === 201 });
    latencyTrend.add(r.timings.duration);

    if (r.status === 201) {
      const id = r.json('id');
      studentIds.push(id);
      createdStudentIds.push(id);
    } else {
      if (!isUnavailable(r)) errorsTotal.add(1);
      studentIds.push(i); // ID de secours : l'inscription sera tentée quand même
    }
  }

  // ────────────────────────────────────────────────────────
  // 2. Création de 10 matières (cours)
  // ────────────────────────────────────────────────────────
  for (let c = 1; c <= 10; c++) {
    let r = http.post(
      `${API_BASE_URL}/teachers/courses`,
      JSON.stringify({
        title: `Matiere ${c} - Iter ${__ITER}`,
        description: `Description ${c}`,
        capacity: 50,
      }),
      { headers: traceHeaders(), timeout: TIMEOUT }
    );

    if (r.status === 201) {
      courseIds.push(r.json('id'));
    } else {
      errorsTotal.add(1);
    }
    latencyTrend.add(r.timings.duration);
  }

  sleep(1);

  // ────────────────────────────────────────────────────────
  // 3. Inscriptions (toujours exécutées, même si students est down)
  // ────────────────────────────────────────────────────────
  for (let sId of studentIds) {
    for (let cId of courseIds) {
      let r = http.post(
        `${API_BASE_URL}/enrollments/enrollments`,
        JSON.stringify({ student_id: sId, course_id: cId }),
        { headers: traceHeaders(), timeout: TIMEOUT }
      );

      check(r, { 'POST /enrollments 201': (res) => res.status === 201 });
      latencyTrend.add(r.timings.duration);

      if (r.status === 201) {
        const eId = r.json('id');
        if (eId) enrollmentIds.push({ enrollmentId: eId });
      } else if (!isUnavailable(r)) {
        errorsTotal.add(1);
      }
    }
  }

  sleep(1);

  // ────────────────────────────────────────────────────────
  // 4. GET ciblés sur le 3ème étudiant
  // ────────────────────────────────────────────────────────
  const targetStudentId = studentIds[2];

  const gets = [
    ['available-courses', 'GET /available-courses 200'],
    ['enrollments',       'GET /student-enrollments 200'],
    ['grades',            'GET /grades 200'],
  ];

  for (const [path, label] of gets) {
    const r = http.get(
      `${API_BASE_URL}/students/students/${targetStudentId}/${path}`,
      { headers: traceHeaders(), timeout: TIMEOUT }
    );
    check(r, { [label]: (res) => res.status === 200 });
    latencyTrend.add(r.timings.duration);
    if (r.status !== 200 && !isUnavailable(r)) errorsTotal.add(1);
  }

  sleep(2);

  // ────────────────────────────────────────────────────────
  // 5. Nettoyage (uniquement ce qui a vraiment été créé)
  // ────────────────────────────────────────────────────────
  for (let item of enrollmentIds) {
    http.del(`${API_BASE_URL}/enrollments/enrollments/${item.enrollmentId}`, null, { headers: traceHeaders(), timeout: TIMEOUT });
  }

  for (let sId of createdStudentIds) {
    http.del(`${API_BASE_URL}/students/students/${sId}`, null, { headers: traceHeaders(), timeout: TIMEOUT });
  }

  for (let cId of courseIds) {
    http.del(`${API_BASE_URL}/teachers/courses/${cId}`, null, { headers: traceHeaders(), timeout: TIMEOUT });
  }

  sleep(5);
}