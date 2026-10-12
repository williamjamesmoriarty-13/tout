# ---------- Stage 1 : build ----------
FROM node:20-alpine AS builder

WORKDIR /build

COPY package.json package-lock.json* ./
RUN apk update && apk upgrade --no-cache && \
    npm ci --no-audit --no-fund

COPY . .

ARG VITE_STUDENT_SERVICE_URL="/api/students"
ARG VITE_TEACHER_ADMIN_SERVICE_URL="/api/teachers"
ARG VITE_ENROLLMENT_SERVICE_URL="/api/enrollments"

ENV VITE_STUDENT_SERVICE_URL=$VITE_STUDENT_SERVICE_URL
ENV VITE_TEACHER_ADMIN_SERVICE_URL=$VITE_TEACHER_ADMIN_SERVICE_URL
ENV VITE_ENROLLMENT_SERVICE_URL=$VITE_ENROLLMENT_SERVICE_URL

RUN npm run build

# ---------- Stage 2 : nginx non-root ----------
FROM nginxinc/nginx-unprivileged:1.27-alpine

USER root
RUN apk update && apk upgrade --no-cache && \
    rm -rf /var/cache/apk/*
USER 101

# Fichier par défaut pour build standard (K8s / Ingress)
ARG NGINX_CONFIG=nginx.conf

COPY --from=builder /build/dist /usr/share/nginx/html
# Copie le fichier désigné par la variable ARG
COPY ${NGINX_CONFIG} /etc/nginx/conf.d/default.conf

EXPOSE 80
