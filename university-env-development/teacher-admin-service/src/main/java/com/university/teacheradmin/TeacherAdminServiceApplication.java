package com.university.teacheradmin;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public final class TeacherAdminServiceApplication {

    private TeacherAdminServiceApplication() {
        // Empêche l'instanciation de cette classe utilitaire
    }

    public static void main(String[] args) {
        SpringApplication.run(TeacherAdminServiceApplication.class, args);
    }
}
