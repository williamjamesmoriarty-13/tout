CREATE TABLE IF NOT EXISTS courses (
    id              BIGSERIAL PRIMARY KEY,
    title           VARCHAR(150) NOT NULL,
    description     VARCHAR(1000),
    capacity        INTEGER NOT NULL CHECK (capacity > 0),
    enrolled_count  INTEGER NOT NULL DEFAULT 0 CHECK (enrolled_count >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS announcements (
    id          BIGSERIAL PRIMARY KEY,
    course_id   BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    text        VARCHAR(2000) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS grades (
    id          BIGSERIAL PRIMARY KEY,
    student_id  BIGINT NOT NULL,
    course_id   BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    value       NUMERIC(4,2) NOT NULL CHECK (value >= 0 AND value <= 20),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_grade_student_course UNIQUE (student_id, course_id)
);

CREATE INDEX IF NOT EXISTS ix_announcements_course_id ON announcements(course_id);
CREATE INDEX IF NOT EXISTS ix_grades_student_id ON grades(student_id);
CREATE INDEX IF NOT EXISTS ix_grades_course_id ON grades(course_id);
