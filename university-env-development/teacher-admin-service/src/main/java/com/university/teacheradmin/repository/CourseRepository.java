package com.university.teacheradmin.repository;

import org.springframework.data.jpa.repository.JpaRepository;

import com.university.teacheradmin.model.Course;

public interface CourseRepository extends JpaRepository<Course, Long> {
}
