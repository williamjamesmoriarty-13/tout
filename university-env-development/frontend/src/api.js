const STUDENT_SERVICE_URL = import.meta.env.VITE_STUDENT_SERVICE_URL || "/api/students";
const TEACHER_ADMIN_SERVICE_URL = import.meta.env.VITE_TEACHER_ADMIN_SERVICE_URL || "/api/teachers";
const ENROLLMENT_SERVICE_URL = import.meta.env.VITE_ENROLLMENT_SERVICE_URL || "/api/enrollments";

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await response.json() : null;
  if (!response.ok) {
    const message = body?.error || `Erreur HTTP ${response.status}`;
    throw new Error(message);
  }
  return body;
}

// --- student-service ---
export const listStudents = () => request(`${STUDENT_SERVICE_URL}/students`);
export const createStudent = (data) =>
  request(`${STUDENT_SERVICE_URL}/students`, { method: "POST", body: JSON.stringify(data) });
export const getAvailableCourses = (studentId) =>
  request(`${STUDENT_SERVICE_URL}/students/${studentId}/available-courses`);
export const getStudentEnrollments = (studentId) =>
  request(`${STUDENT_SERVICE_URL}/students/${studentId}/enrollments`);
export const getStudentGrades = (studentId) =>
  request(`${STUDENT_SERVICE_URL}/students/${studentId}/grades`);

// --- teacher-admin-service ---
export const listCourses = () => request(`${TEACHER_ADMIN_SERVICE_URL}/courses`);
export const createCourse = (data) =>
  request(`${TEACHER_ADMIN_SERVICE_URL}/courses`, { method: "POST", body: JSON.stringify(data) });

// --- enrollment-service ---
export const createEnrollment = (data) =>
  request(`${ENROLLMENT_SERVICE_URL}/enrollments`, { method: "POST", body: JSON.stringify(data) });
