package com.university.teacheradmin.controller;

import java.util.List;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.university.teacheradmin.dto.CourseCreateRequest;
import com.university.teacheradmin.dto.CourseResponse;
import com.university.teacheradmin.exception.ConflictException;
import com.university.teacheradmin.exception.ResourceNotFoundException;
import com.university.teacheradmin.model.Course;
import com.university.teacheradmin.repository.CourseRepository;

import jakarta.validation.Valid;

@RestController
@RequestMapping("/hehe")
public class DemoController {

    private final CourseRepository courseRepository;
    private static final String MSG_COURS_INTROUVABLE =  "Cours introuvable";
    public DemoController(CourseRepository courseRepository) {
        this.courseRepository = courseRepository;
    }

    @PostMapping
    public ResponseEntity<CourseResponse> createCourse(@Valid @RequestBody CourseCreateRequest request) {
        Course course = new Course(request.getTitle(), request.getDescription(), request.getCapacity());
        courseRepository.save(course);
        return ResponseEntity.status(HttpStatus.CREATED).body(CourseResponse.from(course));
    }

    @GetMapping
    public List<CourseResponse> listCourses() {
        return courseRepository.findAll().stream().map(CourseResponse::from).toList();
    }

    @GetMapping("/{id}")
    public CourseResponse getCourse(@PathVariable Long id) {
        Course course = courseRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException(MSG_COURS_INTROUVABLE));
        return CourseResponse.from(course);
    }

    @GetMapping("/{id}/capacity")
    public Map<String, Integer> getCapacity(@PathVariable Long id) {
        Course course = courseRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException(MSG_COURS_INTROUVABLE));
        return Map.of(
                "capacity", course.getCapacity(),
                "enrolledCount", course.getEnrolledCount(),
                "availableSeats", course.availableSeats()
        );
    }

    /**
     * Réserve une place dans le cours (appelé par enrollment-service lors
     * d'une inscription). Opération idempotente-safe grâce à la vérification
     * de capacité faite dans la même transaction.
     */
    @PostMapping("/{id}/reserve-seat")
    @Transactional
    public ResponseEntity<CourseResponse> reserveSeat(@PathVariable Long id) {
        Course course = courseRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException(MSG_COURS_INTROUVABLE));
        if (course.availableSeats() <= 0) {
            throw new ConflictException("Ce cours est complet");
        }
        course.setEnrolledCount(course.getEnrolledCount() + 1);
        courseRepository.save(course);
        return ResponseEntity.ok(CourseResponse.from(course));
    }

    /**
     * Libère une place (appelé par enrollment-service lors d'une annulation
     * d'inscription, ou en compensation d'une erreur).
     */
    @PostMapping("/{id}/release-seat")
    @Transactional
    public ResponseEntity<CourseResponse> releaseSeat(@PathVariable Long id) {
        Course course = courseRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException(MSG_COURS_INTROUVABLE));
        if (course.getEnrolledCount() > 0) {
            course.setEnrolledCount(course.getEnrolledCount() - 1);
            courseRepository.save(course);
        }
        return ResponseEntity.ok(CourseResponse.from(course));
    }
}
