package com.university.teacheradmin.controller;

import static org.hamcrest.Matchers.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import com.university.teacheradmin.dto.CourseCreateRequest;
import com.university.teacheradmin.exception.GlobalExceptionHandler;
import com.university.teacheradmin.model.Course;
import com.university.teacheradmin.repository.CourseRepository;

import tools.jackson.databind.json.JsonMapper;

/**
 * Tests unitaires — CourseController (teacher-admin-service)
 *
 * Stratégie :
 * - MockMvc standalone (pas de contexte Spring complet, démarrage instantané)
 * - CourseRepository mocké avec Mockito — aucune base de données réelle
 * - On teste : codes HTTP, corps JSON, gestion des erreurs (404, 409),
 *   validation Bean Validation, logique de réservation/libération de places
 *
 * Dépendances Maven à ajouter dans pom.xml (scope test) :
 *   spring-boot-starter-test (déjà présent)
 *   → inclut JUnit 5, Mockito, MockMvc, AssertJ, Hamcrest
 *
 * Lancer :
 *   mvn test -pl teacher-admin-service
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("CourseController — Tests unitaires")
class CourseControllerTest {

    @Mock
    private CourseRepository courseRepository;

    @InjectMocks
    private CourseController courseController;

    private MockMvc mockMvc;
    private final JsonMapper mapper = JsonMapper.builder().build();

    // ── Helpers ────────────────────────────────────────────────────────────────

    private Course buildCourse(Long id, String title, int capacity, int enrolled) {
        Course c = new Course(title, "Description de test", capacity);
        c.setEnrolledCount(enrolled);
        // Injection de l'ID via réflexion (champ privé sans setter)
        try {
            var field = Course.class.getDeclaredField("id");
            field.setAccessible(true);
            field.set(c, id);
            var createdAt = Course.class.getDeclaredField("createdAt");
            createdAt.setAccessible(true);
            createdAt.set(c, OffsetDateTime.now());
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        return c;
    }

    private String json(Object o) throws Exception {
        return mapper.writeValueAsString(o);
    }

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders
            .standaloneSetup(courseController)
            .setControllerAdvice(new GlobalExceptionHandler())
            .build();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // POST /courses — Création
    // ══════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("POST /courses")
    class CreateCourse {

        @Test
        @DisplayName("Création valide → 201 avec le corps attendu")
        void createValid_returns201() throws Exception {
            Course saved = buildCourse(1L, "Algorithmique", 30, 0);
            when(courseRepository.save(any(Course.class))).thenReturn(saved);

            CourseCreateRequest req = new CourseCreateRequest();
            req.setTitle("Algorithmique");
            req.setDescription("Cours de test");
            req.setCapacity(30);

            mockMvc.perform(post("/courses")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(json(req)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.title").value("Algorithmique"))
                .andExpect(jsonPath("$.capacity").value(30))
                .andExpect(jsonPath("$.enrolledCount").value(0))
                .andExpect(jsonPath("$.availableSeats").value(30));
        }

        @Test
        @DisplayName("Titre vide → 400")
        void emptyTitle_returns400() throws Exception {
            CourseCreateRequest req = new CourseCreateRequest();
            req.setTitle("");
            req.setCapacity(30);

            mockMvc.perform(post("/courses")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(json(req)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").exists());
        }

        @Test
        @DisplayName("Capacité nulle → 400")
        void nullCapacity_returns400() throws Exception {
            CourseCreateRequest req = new CourseCreateRequest();
            req.setTitle("Cours valide");
            req.setCapacity(null);

            mockMvc.perform(post("/courses")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(json(req)))
                .andExpect(status().isBadRequest());
        }

        @Test
        @DisplayName("Capacité à 0 → 400")
        void zeroCapacity_returns400() throws Exception {
            CourseCreateRequest req = new CourseCreateRequest();
            req.setTitle("Cours");
            req.setCapacity(0);

            mockMvc.perform(post("/courses")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(json(req)))
                .andExpect(status().isBadRequest());
        }

        @Test
        @DisplayName("Corps JSON absent → 400")
        void emptyBody_returns400() throws Exception {
            mockMvc.perform(post("/courses")
                    .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isBadRequest());
        }

        @Test
        @DisplayName("Titre trop long (> 150 car.) → 400")
        void titleTooLong_returns400() throws Exception {
            CourseCreateRequest req = new CourseCreateRequest();
            req.setTitle("A".repeat(151));
            req.setCapacity(30);

            mockMvc.perform(post("/courses")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(json(req)))
                .andExpect(status().isBadRequest());
        }

        @Test
        @DisplayName("enrolledCount est 0 à la création")
        void enrolledCountIsZeroOnCreate() throws Exception {
            Course saved = buildCourse(1L, "Nouveau cours", 20, 0);
            when(courseRepository.save(any())).thenReturn(saved);

            CourseCreateRequest req = new CourseCreateRequest();
            req.setTitle("Nouveau cours");
            req.setCapacity(20);

            mockMvc.perform(post("/courses")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(json(req)))
                .andExpect(jsonPath("$.enrolledCount").value(0));
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // GET /courses — Liste
    // ══════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("GET /courses")
    class ListCourses {

        @Test
        @DisplayName("Liste vide → 200 avec tableau vide")
        void emptyList_returns200() throws Exception {
            when(courseRepository.findAll()).thenReturn(List.of());

            mockMvc.perform(get("/courses"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$").isEmpty());
        }

        @Test
        @DisplayName("Retourne tous les cours avec availableSeats calculé")
        void listWithCourses_returnsAll() throws Exception {
            when(courseRepository.findAll()).thenReturn(List.of(
                buildCourse(1L, "Algo", 30, 5),
                buildCourse(2L, "BDD", 20, 20)
            ));

            mockMvc.perform(get("/courses"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[0].availableSeats").value(25))
                .andExpect(jsonPath("$[1].availableSeats").value(0));
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // GET /courses/<id> — Détail
    // ══════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("GET /courses/{id}")
    class GetCourse {

        @Test
        @DisplayName("Cours existant → 200 avec les données")
        void existingCourse_returns200() throws Exception {
            when(courseRepository.findById(1L))
                .thenReturn(Optional.of(buildCourse(1L, "Algo", 30, 5)));

            mockMvc.perform(get("/courses/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("Algo"))
                .andExpect(jsonPath("$.availableSeats").value(25));
        }

        @Test
        @DisplayName("Cours inexistant → 404")
        void nonExistentCourse_returns404() throws Exception {
            when(courseRepository.findById(999L)).thenReturn(Optional.empty());

            mockMvc.perform(get("/courses/999"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").exists());
        }

        @Test
        @DisplayName("404 ne contient pas de stacktrace")
        void notFound_noStacktrace() throws Exception {
            when(courseRepository.findById(999L)).thenReturn(Optional.empty());

            var result = mockMvc.perform(get("/courses/999"))
                .andReturn();
            String body = result.getResponse().getContentAsString();
            assert !body.contains("at com.university");
            assert !body.contains("Exception");
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // GET /courses/<id>/capacity
    // ══════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("GET /courses/{id}/capacity")
    class GetCapacity {

        @Test
        @DisplayName("Retourne capacity, enrolledCount et availableSeats")
        void returnsAllCapacityFields() throws Exception {
            when(courseRepository.findById(1L))
                .thenReturn(Optional.of(buildCourse(1L, "Algo", 30, 12)));

            mockMvc.perform(get("/courses/1/capacity"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.capacity").value(30))
                .andExpect(jsonPath("$.enrolledCount").value(12))
                .andExpect(jsonPath("$.availableSeats").value(18));
        }

        @Test
        @DisplayName("Cours inexistant → 404")
        void nonExistent_returns404() throws Exception {
            when(courseRepository.findById(999L)).thenReturn(Optional.empty());
            mockMvc.perform(get("/courses/999/capacity"))
                .andExpect(status().isNotFound());
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // POST /courses/<id>/reserve-seat
    // ══════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("POST /courses/{id}/reserve-seat")
    class ReserveSeat {

        @Test
        @DisplayName("Place disponible → 200, enrolledCount incrémenté")
        void availableSeat_incrementsEnrolledCount() throws Exception {
            Course course = buildCourse(1L, "Algo", 30, 5);
            when(courseRepository.findById(1L)).thenReturn(Optional.of(course));
            when(courseRepository.save(any(Course.class))).thenAnswer(inv -> inv.getArgument(0));

            mockMvc.perform(post("/courses/1/reserve-seat"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.enrolledCount").value(6))
                .andExpect(jsonPath("$.availableSeats").value(24));
        }

        @Test
        @DisplayName("Cours complet → 409")
        void fullCourse_returns409() throws Exception {
            Course full = buildCourse(1L, "Algo", 30, 30);
            when(courseRepository.findById(1L)).thenReturn(Optional.of(full));

            mockMvc.perform(post("/courses/1/reserve-seat"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error").exists());
        }

        @Test
        @DisplayName("Cours inexistant → 404")
        void nonExistent_returns404() throws Exception {
            when(courseRepository.findById(999L)).thenReturn(Optional.empty());
            mockMvc.perform(post("/courses/999/reserve-seat"))
                .andExpect(status().isNotFound());
        }

        @Test
        @DisplayName("save() est bien appelé après réservation")
        void callsSaveAfterReservation() throws Exception {
            Course course = buildCourse(1L, "Algo", 30, 5);
            when(courseRepository.findById(1L)).thenReturn(Optional.of(course));
            when(courseRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

            mockMvc.perform(post("/courses/1/reserve-seat"))
                .andExpect(status().isOk());

            verify(courseRepository, times(1))
                .save(argThat(c -> c.getEnrolledCount() == 6));
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // POST /courses/<id>/release-seat
    // ══════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("POST /courses/{id}/release-seat")
    class ReleaseSeat {

        @Test
        @DisplayName("Libération normale → 200, enrolledCount décrémenté")
        void releaseSeat_decrementsCount() throws Exception {
            Course course = buildCourse(1L, "Algo", 30, 10);
            when(courseRepository.findById(1L)).thenReturn(Optional.of(course));
            when(courseRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

            mockMvc.perform(post("/courses/1/release-seat"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.enrolledCount").value(9))
                .andExpect(jsonPath("$.availableSeats").value(21));
        }

        @Test
        @DisplayName("enrolledCount à 0 : pas de décrémentation négative")
        void releaseWhenZero_noNegativeCount() throws Exception {
            Course course = buildCourse(1L, "Algo", 30, 0);
            when(courseRepository.findById(1L)).thenReturn(Optional.of(course));

            mockMvc.perform(post("/courses/1/release-seat"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.enrolledCount").value(0));

            // save ne doit PAS être appelé si enrolledCount est déjà 0
            verify(courseRepository, never()).save(any());
        }

        @Test
        @DisplayName("Cours inexistant → 404")
        void nonExistent_returns404() throws Exception {
            when(courseRepository.findById(999L)).thenReturn(Optional.empty());
            mockMvc.perform(post("/courses/999/release-seat"))
                .andExpect(status().isNotFound());
        }
    }
}
