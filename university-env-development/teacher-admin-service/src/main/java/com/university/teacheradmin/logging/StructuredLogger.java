package com.university.teacheradmin.logging;

import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Logger JSON structuré, un objet JSON par ligne (JSON Lines), au format
 * commun partagé avec student-service et enrollment-service (Python).
 * Volontairement minimaliste (pas de dépendance logstash-encoder) pour
 * garder l'image finale légère.
 */
public class StructuredLogger {

    private static final String SERVICE_NAME = "teacher-admin-service";
    private final Logger slf4jLogger;

    public StructuredLogger(Class<?> clazz) {
        this.slf4jLogger = LoggerFactory.getLogger(clazz);
    }

    public void info(String event, Map<String, Object> fields) {
        slf4jLogger.info(toJson("INFO", event, fields));
    }

    public void warn(String event, Map<String, Object> fields) {
        slf4jLogger.warn(toJson("WARN", event, fields));
    }

    public void error(String event, Map<String, Object> fields) {
        slf4jLogger.error(toJson("ERROR", event, fields));
    }

    private String toJson(String level, String event, Map<String, Object> fields) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("timestamp", DateTimeFormatter.ISO_INSTANT.format(Instant.now()));
        payload.put("level", level);
        payload.put("service", SERVICE_NAME);
        payload.put("event", event);
        if (fields != null) {
            payload.putAll(fields);
        }
        return toJsonString(payload);
    }

    private String toJsonString(Map<String, Object> map) {
        StringBuilder sb = new StringBuilder('{');      
        boolean first = true;
        for (Map.Entry<String, Object> entry : map.entrySet()) {
            if (!first) {
                sb.append(',');                        
            }
            first = false;
            sb.append('"').append(escape(entry.getKey())).append("\":");
            Object value = entry.getValue();
            if (value == null) {
                sb.append("null");                      
            } else if (value instanceof Number || value instanceof Boolean) {
                sb.append(value);
            } else {
                sb.append('"').append(escape(String.valueOf(value))).append('"');   
            }
        }
        sb.append('}');                                 
        return sb.toString();
    }
    private String escape(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ");
    }
}
