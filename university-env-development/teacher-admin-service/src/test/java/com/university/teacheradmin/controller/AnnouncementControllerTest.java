package com.university.teacheradmin.controller;

import static org.hamcrest.Matchers.hasSize;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.OffsetDateTime;
import java.util.List;

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

import com.university.teacheradmin.dto.AnnouncementCreateRequest;
import com.university.teacheradmin.exception.GlobalExceptionHandler;
import com.university.teacheradmin.model.Announcement;
import com.university.teacheradmin.repository.AnnouncementRepository;
import com.university.teacheradmin.repository.CourseRepository;

import tools.jackson.databind.json.JsonMapper;

/**
 * Tests unitaires — AnnouncementController
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AnnouncementController — Tests unitaires")
class AnnouncementControllerTest {

    @Mock private AnnouncementRepository announcementRepository;
    @Mock private CourseRepository courseRepository;

    @InjectMocks private AnnouncementController announcementController;

    private MockMvc mvc;
    private final JsonMapper mapper = JsonMapper.builder().build();

    private Announcement buildAnnouncement(Long id, Long courseId, String text) {
        Announcement a = new Announcement(courseId, text);
        try {
            var f = Announcement.class.getDeclaredField("id");
            f.setAccessible(true);
            f.set(a, id);
            var ca = Announcement.class.getDeclaredField("createdAt");
            ca.setAccessible(true);
            ca.set(a, OffsetDateTime.now()); // corrigé : cible "a", pas le Field "ca"
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        return a;
    }

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders
            .standaloneSetup(announcementController)
            .setControllerAdvice(new GlobalExceptionHandler())
            .build();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // POST /announcements
    // ══════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("POST /announcements — Création d'annonce")
    class CreateAnnouncement {

        @Test
        @DisplayName("Annonce valide → 201")
        void validAnnouncement_returns201() throws Exception {
            when(courseRepository.existsById(1L)).thenReturn(true);
            when(announcementRepository.save(any())).thenAnswer(inv -> {
                Announcement a = inv.getArgument(0);
                return buildAnnouncement(1L, a.getCourseId(), a.getText());
            });

            AnnouncementCreateRequest req = new AnnouncementCreateRequest();
            req.setCourseId(1L);
            req.setText("Pas de cours vendredi.");

            mvc.perform(post("/announcements")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(mapper.writeValueAsString(req)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.text").value("Pas de cours vendredi."));
        }

        @Test
        @DisplayName("Cours inexistant → 404")
        void nonExistentCourse_returns404() throws Exception {
            when(courseRepository.existsById(99L)).thenReturn(false);

            AnnouncementCreateRequest req = new AnnouncementCreateRequest();
            req.setCourseId(99L);
            req.setText("Test");

            mvc.perform(post("/announcements")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(mapper.writeValueAsString(req)))
                .andExpect(status().isNotFound());
        }

        @Test
        @DisplayName("Texte vide → 400")
        void emptyText_returns400() throws Exception {
            AnnouncementCreateRequest req = new AnnouncementCreateRequest();
            req.setCourseId(1L);
            req.setText("");

            mvc.perform(post("/announcements")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(mapper.writeValueAsString(req)))
                .andExpect(status().isBadRequest());
        }

        @Test
        @DisplayName("courseId manquant → 400")
        void missingCourseId_returns400() throws Exception {
            AnnouncementCreateRequest req = new AnnouncementCreateRequest();
            req.setText("Texte valide");

            mvc.perform(post("/announcements")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(mapper.writeValueAsString(req)))
                .andExpect(status().isBadRequest());
        }

        @Test
        @DisplayName("Texte > 2000 caractères → 400")
        void textTooLong_returns400() throws Exception {
            AnnouncementCreateRequest req = new AnnouncementCreateRequest();
            req.setCourseId(1L);
            req.setText("A".repeat(2001));

            mvc.perform(post("/announcements")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(mapper.writeValueAsString(req)))
                .andExpect(status().isBadRequest());
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // GET /announcements
    // ══════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("GET /announcements — Liste des annonces")
    class ListAnnouncements {

        @Test
        @DisplayName("Sans filtre → toutes les annonces")
        void noFilter_returnsAll() throws Exception {
            when(announcementRepository.findAll()).thenReturn(List.of(
                buildAnnouncement(1L, 1L, "Annonce 1"),
                buildAnnouncement(2L, 2L, "Annonce 2")
            ));

            mvc.perform(get("/announcements"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)));
        }

        @Test
        @DisplayName("Filtre par courseId → annonces du cours uniquement")
        void filterByCourseId_returnsCourseAnnouncements() throws Exception {
            when(announcementRepository.findByCourseId(1L)).thenReturn(List.of(
                buildAnnouncement(1L, 1L, "Cours annulé")
            ));

            mvc.perform(get("/announcements?courseId=1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(1)))
                .andExpect(jsonPath("$[0].text").value("Cours annulé"));
        }
    }
}
