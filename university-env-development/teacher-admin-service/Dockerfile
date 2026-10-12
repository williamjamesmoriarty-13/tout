# ---------- Stage 1 : build Maven ----------
FROM maven:3.9-eclipse-temurin-21-alpine AS builder

WORKDIR /build

COPY pom.xml .
# Téléchargement optimisé des dépendances
RUN mvn -B -q dependency:go-offline

COPY src ./src
RUN mvn -B -q clean package -DskipTests

# ---------- Stage 2 : image finale minimale ----------
FROM eclipse-temurin:21-jre-alpine

# Patch de sécurité OS + suppression des caches apk
RUN apk update && apk upgrade --no-cache && \
    rm -rf /var/cache/apk/*

# Utilisateur non-root sécurisé
RUN addgroup -S -g 1000 appgroup && \
    adduser -S -u 1000 -G appgroup -s /sbin/nologin appuser

WORKDIR /app

COPY --chown=appuser:appgroup --from=builder /build/target/teacher-admin-service.jar ./app.jar

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD nc -z localhost 8080 || exit 1

ENTRYPOINT ["java", \
    "-XX:MaxRAMPercentage=75.0", \
    "-Djava.security.egd=file:/dev/./urandom", \
    "-Duser.timezone=UTC", \
    "-Dfile.encoding=UTF-8", \
    "-jar", "app.jar"]