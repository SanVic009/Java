package com.anticheat.service;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.ExamRequest;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * HTTP client for communicating with the Python CV service.
 */
public class AnalysisClient {
    private static final String DEFAULT_BASE_URL = "http://localhost:8000";
    private static final String ANALYZE_ENDPOINT = "/analyze";
    private static final Duration DEFAULT_TIMEOUT = Duration.ofMinutes(30); // Long timeout for video processing

    private final String baseUrl;
    private final HttpClient httpClient;
    private final Gson gson;

    public AnalysisClient() {
        this(DEFAULT_BASE_URL);
    }

    public AnalysisClient(String baseUrl) {
        this.baseUrl = baseUrl;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(30))
                .build();
        this.gson = new GsonBuilder()
                .setPrettyPrinting()
                .create();
    }

    /**
     * Send exam video for analysis and receive results.
     *
     * @param request The exam analysis request
     * @return Analysis response with suspicious intervals
     * @throws AnalysisException if the request fails
     */
    public AnalysisResponse analyze(ExamRequest request) throws AnalysisException {
        String requestJson = gson.toJson(request);
        
        System.out.println("Sending analysis request to Python CV service...");
        System.out.println("Exam ID: " + request.getExamId());
        System.out.println("Video: " + request.getVideoPath());
        System.out.println("Seats configured: " + request.getSeatMap().size());

        try {
            HttpRequest httpRequest = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + ANALYZE_ENDPOINT))
                    .header("Content-Type", "application/json")
                    .timeout(DEFAULT_TIMEOUT)
                    .POST(HttpRequest.BodyPublishers.ofString(requestJson))
                    .build();

            HttpResponse<String> response = httpClient.send(httpRequest, 
                    HttpResponse.BodyHandlers.ofString());

            if (response.statusCode() != 200) {
                throw new AnalysisException("Analysis failed with status: " + response.statusCode() 
                        + ", body: " + response.body());
            }

            return gson.fromJson(response.body(), AnalysisResponse.class);

        } catch (AnalysisException e) {
            throw e;
        } catch (Exception e) {
            throw new AnalysisException("Failed to communicate with CV service: " + e.getMessage(), e);
        }
    }

    /**
     * Check if the Python CV service is available.
     *
     * @return true if service is healthy
     */
    public boolean healthCheck() {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/health"))
                    .timeout(Duration.ofSeconds(5))
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(request, 
                    HttpResponse.BodyHandlers.ofString());

            return response.statusCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * Custom exception for analysis failures.
     */
    public static class AnalysisException extends Exception {
        public AnalysisException(String message) {
            super(message);
        }

        public AnalysisException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
