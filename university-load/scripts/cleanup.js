// ============================================================
// cleanup.js — Nettoyage complet et propre via l'API Gateway
// Ordre : 
//   1. Supprimer tous les enrollments (décrémente le compteur)
//   2. Supprimer tous les students
//   3. Supprimer tous les courses
// ============================================================

import http from 'k6/http';
import { check, sleep } from 'k6';
import { API_BASE_URL, TIMEOUT } from './config.js';

export const options = {
  vus: 1,
  iterations: 1,
};

export default function () {
  console.log("=== DÉBUT DU NETTOYAGE PROPRE ===");

  // 1. Supprimer tous les Enrollments
  let resEnrollments = http.get(`${API_BASE_URL}/enrollments/enrollments`);
  if (resEnrollments.status === 200) {
    const enrollments = resEnrollments.json();
    console.log(`Suppression de ${enrollments.length} inscription(s)...`);
    for (let e of enrollments) {
      http.del(`${API_BASE_URL}/enrollments/enrollments/${e.id}`, null, { timeout: TIMEOUT });
      sleep(0.02);
    }
  }

  // Petite pause pour laisser le temps aux services de synchroniser les compteurs
  sleep(1);

  // 2. Supprimer tous les Students
  let resStudents = http.get(`${API_BASE_URL}/students/students`);
  if (resStudents.status === 200) {
    const students = resStudents.json();
    console.log(`Suppression de ${students.length} étudiant(s)...`);
    for (let s of students) {
      http.del(`${API_BASE_URL}/students/students/${s.id}`, null, { timeout: TIMEOUT });
      sleep(0.02);
    }
  }

  sleep(1);

  // 3. Supprimer tous les Courses
  let resCourses = http.get(`${API_BASE_URL}/teachers/courses`);
  if (resCourses.status === 200) {
    const courses = resCourses.json();
    console.log(`Suppression de ${courses.length} cours/matière(s)...`);
    for (let c of courses) {
      let r = http.del(`${API_BASE_URL}/teachers/courses/${c.id}`, null, { timeout: TIMEOUT });
      console.log(`Suppression course ${c.id} (${c.title}) -> Status: ${r.status}`);
      sleep(0.02);
    }
  }

  console.log("=== FIN DU NETTOYAGE PROPRE ===");
}