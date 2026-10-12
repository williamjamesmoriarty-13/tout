package com.university.teacheradmin.controller;

import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.university.teacheradmin.dto.AnnouncementCreateRequest;
import com.university.teacheradmin.exception.ResourceNotFoundException;
import com.university.teacheradmin.model.Announcement;
import com.university.teacheradmin.repository.AnnouncementRepository;
import com.university.teacheradmin.repository.CourseRepository;

import jakarta.validation.Valid;

@RestController
@RequestMapping("/announcements")
public class AnnouncementController {

    private final AnnouncementRepository announcementRepository;
    private final CourseRepository courseRepository;

    public AnnouncementController(AnnouncementRepository announcementRepository, CourseRepository courseRepository) {
        this.announcementRepository = announcementRepository;
        this.courseRepository = courseRepository;
    }

    @PostMapping
    public ResponseEntity<Announcement> createAnnouncement(@Valid @RequestBody AnnouncementCreateRequest request) {
        if (!courseRepository.existsById(request.getCourseId())) {
            throw new ResourceNotFoundException("Cours introuvable");
        }
        Announcement announcement = new Announcement(request.getCourseId(), request.getText());
        announcementRepository.save(announcement);
        return ResponseEntity.status(HttpStatus.CREATED).body(announcement);
    }

    @GetMapping
    public List<Announcement> listAnnouncements(@RequestParam(required = false) Long courseId) {
        if (courseId != null) {
            return announcementRepository.findByCourseId(courseId);
        }
        return announcementRepository.findAll();
    }
}
