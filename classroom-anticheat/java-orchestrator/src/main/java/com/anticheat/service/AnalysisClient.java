package com.anticheat.service;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.ExamRequest;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * HTTP client for communicating with the Python CV service.
 */
public class AnalysisClient {
    private static final String DEFAULT_BASE_URL = "http://localhost:8000";
    private static final String ANALYZE_ENDPOINT = "/analyze";
    private static final String STATUS_ENDPOINT_PREFIX = "/status/";
    private static final String RESULT_ENDPOINT_PREFIX = "/result/";
    private static final Duration DEFAULT_TIMEOUT = Duration.ofMinutes(30); // Long timeout for video processing
    private static final Duration POLL_INTERVAL = Duration.ofSeconds(2);

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
            .version(HttpClient.Version.HTTP_1_1)
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
    public String submitAnalysis(ExamRequest request) throws AnalysisException {
        String requestJson = gson.toJson(request);

        System.out.println("Submitting analysis job to Python CV service...");
        System.out.println("Exam ID: " + request.getExamId());
        System.out.println("Video: " + request.getVideoPath());
        System.out.println("Payload: " + requestJson);

        try {
            HttpRequest httpRequest = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + ANALYZE_ENDPOINT))
                    .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                    .timeout(DEFAULT_TIMEOUT)
                .POST(HttpRequest.BodyPublishers.ofByteArray(requestJson.getBytes(StandardCharsets.UTF_8)))
                    .build();

            HttpResponse<String> response = httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofString());

            if (response.statusCode() != 200) {
                throw new AnalysisException("Job submission failed with status: " + response.statusCode()
                        + ", body: " + response.body());
            }

            // Expected JSON: { "job_id": "..." }
            return gson.fromJson(response.body(), java.util.Map.class).get("job_id").toString();
        } catch (AnalysisException e) {
            throw e;
        } catch (Exception e) {
            throw new AnalysisException("Failed to submit analysis job: " + e.getMessage(), e);
        }
    }

    public AnalysisResponse waitForResult(String jobId) throws AnalysisException {
        long start = System.currentTimeMillis();
        while (true) {
            if (System.currentTimeMillis() - start > DEFAULT_TIMEOUT.toMillis()) {
                throw new AnalysisException("Timed out waiting for job result: " + jobId);
            }

            JobStatus status = getJobStatus(jobId);
            if (status.status.equalsIgnoreCase("completed")) {
                return getResult(jobId);
            }
            if (status.status.equalsIgnoreCase("failed")) {
                throw new AnalysisException("Job failed: " + status.message);
            }

            System.out.println("Job " + jobId + " status=" + status.status + " progress=" + status.progress);
            try {
                Thread.sleep(POLL_INTERVAL.toMillis());
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                throw new AnalysisException("Interrupted while polling job: " + jobId, ie);
            }
        }
    }

    private AnalysisResponse getResult(String jobId) throws AnalysisException {
        try {
            HttpRequest httpRequest = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + RESULT_ENDPOINT_PREFIX + jobId))
                    .header("Content-Type", "application/json")
                    .timeout(DEFAULT_TIMEOUT)
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                throw new AnalysisException("Get result failed with status: " + response.statusCode()
                        + ", body: " + response.body());
            }

            // Expected JSON: { job_id, status, result: { ...AnalysisResponse... }, error }
            java.util.Map<?, ?> body = gson.fromJson(response.body(), java.util.Map.class);
            Object resultObj = body.get("result");
            if (resultObj == null) {
                throw new AnalysisException("Job result not present yet for job_id: " + jobId);
            }
            // Re-serialize resultObj back to JSON string to parse as AnalysisResponse.
            String resultJson = gson.toJson(resultObj);
            return gson.fromJson(resultJson, AnalysisResponse.class);
        } catch (Exception e) {
            throw new AnalysisException("Failed to fetch result for job: " + jobId + " (" + e.getMessage() + ")", e);
        }
    }

    private JobStatus getJobStatus(String jobId) throws AnalysisException {
        try {
            HttpRequest httpRequest = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + STATUS_ENDPOINT_PREFIX + jobId))
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofSeconds(10))
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                throw new AnalysisException("Get status failed with status: " + response.statusCode()
                        + ", body: " + response.body());
            }

            java.util.Map<?, ?> body = gson.fromJson(response.body(), java.util.Map.class);
            JobStatus status = new JobStatus();
            status.jobId = jobId;
            status.status = body.get("status").toString();
            Object progressObj = body.get("progress");
            status.progress = progressObj == null ? 0.0 : Double.parseDouble(progressObj.toString());
            Object messageObj = body.get("message");
            status.message = messageObj == null ? null : messageObj.toString();
            return status;
        } catch (Exception e) {
            throw new AnalysisException("Failed to fetch status for job: " + jobId + " (" + e.getMessage() + ")", e);
        }
    }

    private static class JobStatus {
        String jobId;
        String status;
        double progress;
        String message;
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
