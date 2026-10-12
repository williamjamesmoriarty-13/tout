package com.university.teacheradmin.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import com.university.teacheradmin.model.Grade;

public interface GradeRepository extends JpaRepository<Grade, Long> {
    List<Grade> findByStudentId(Long studentId);

    Optional<Grade> findByStudentIdAndCourseId(Long studentId, Long courseId);
}
