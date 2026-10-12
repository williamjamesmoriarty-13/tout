package com.university.teacheradmin.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import com.university.teacheradmin.model.Announcement;

@SuppressWarnings("PMD.ImplicitFunctionalInterface")
public interface AnnouncementRepository extends JpaRepository<Announcement, Long> {
    List<Announcement> findByCourseId(Long courseId);
}