package com.university.teacheradmin.dto;

import java.time.OffsetDateTime;

import com.university.teacheradmin.model.Course;

public class CourseResponse {
    private Long id;
    private String title;
    private String description;
    private Integer capacity;
    private Integer enrolledCount;
    private Integer availableSeats;
    private OffsetDateTime createdAt;

    public static CourseResponse from(Course course) {
        CourseResponse dto = new CourseResponse();
        dto.id = course.getId();
        dto.title = course.getTitle();
        dto.description = course.getDescription();
        dto.capacity = course.getCapacity();
        dto.enrolledCount = course.getEnrolledCount();
        dto.availableSeats = course.availableSeats();
        dto.createdAt = course.getCreatedAt();
        return dto;
    }

    public Long getId() {
        return id;
    }

    public String getTitle() {
        return title;
    }

    public String getDescription() {
        return description;
    }

    public Integer getCapacity() {
        return capacity;
    }

    public Integer getEnrolledCount() {
        return enrolledCount;
    }

    public Integer getAvailableSeats() {
        return availableSeats;
    }

    public OffsetDateTime getCreatedAt() {
        return createdAt;
    }
}
