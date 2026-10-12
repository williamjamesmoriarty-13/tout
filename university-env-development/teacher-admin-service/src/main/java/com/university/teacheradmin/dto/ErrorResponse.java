package com.university.teacheradmin.dto;

import java.util.Map;

public class ErrorResponse {
    private String error;
    private Map<String, String> details;

    public ErrorResponse(String error) {
        this.error = error;
    }

    public ErrorResponse(String error, Map<String, String> details) {
        this.error = error;
        this.details = details;
    }

    public String getError() {
        return error;
    }

    public Map<String, String> getDetails() {
        return details;
    }
}
