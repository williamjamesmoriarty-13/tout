package com.university.teacheradmin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public class AnnouncementCreateRequest {

    @NotNull(message = "courseId est obligatoire")
    private Long courseId;

    @NotBlank(message = "Le texte est obligatoire")
    @Size(max = 2000, message = "Le texte ne doit pas dépasser 2000 caractères")
    private String text;

    public Long getCourseId() {
        return courseId;
    }

    public void setCourseId(Long courseId) {
        this.courseId = courseId;
    }

    public String getText() {
        return text;
    }

    public void setText(String text) {
        this.text = text;
    }
}
