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
import java.util.Map;

/**
 * HTTP client for communicating with the Python CV service.
 */
public class AnalysisClient {
    private static final String DEFAULT_BASE_URL = "http://localhost:8000";
    private static final String ANALYZE_ENDPOINT = "/analyze";
    private static final String STATUS_ENDPOINT_PREFIX = "/status/";
    private static final String RESULT_ENDPOINT_PREFIX = "/result/";
    private static final Duration DEFAULT_TIMEOUT = Duration.ofMinutes(30); // Long timeout for video processing
    private static final int POLL_INTERVAL_MS = 3000;
    private static final int MAX_POLL_ATTEMPTS = 2400;

    private final String baseUrl;
    private final HttpClient httpClient;
    private final Gson gson;
    private final int pollIntervalMs;
    private final int maxPollAttempts;

    public AnalysisClient() {
        this(DEFAULT_BASE_URL, POLL_INTERVAL_MS, MAX_POLL_ATTEMPTS);
    }

    public AnalysisClient(String baseUrl) {
        this(baseUrl, POLL_INTERVAL_MS, MAX_POLL_ATTEMPTS);
    }

    public AnalysisClient(String baseUrl, int pollIntervalMs, int maxPollAttempts) {
        this.baseUrl = baseUrl;
        this.pollIntervalMs = Math.max(250, pollIntervalMs);
        this.maxPollAttempts = Math.max(1, maxPollAttempts);
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
        int pollCount = 0;
        while (pollCount < maxPollAttempts) {
            pollCount += 1;

            JobStatus status = getJobStatus(jobId);
            if (status.status.equalsIgnoreCase("completed")) {
                return getResult(jobId);
            }
            if (status.status.equalsIgnoreCase("failed")) {
                throw new AnalysisException(getFailedJobMessage(jobId, status.message));
            }

            if (pollCount % 10 == 0) {
                String msg = status.message == null ? "" : status.message;
                int pct = (int) Math.round(status.progress * 100.0);
                System.out.println(
                        "[Poll " + pollCount + "/" + maxPollAttempts + "] Status: "
                                + status.status + " — " + msg + " (" + pct + "%)"
                );
            }

            try {
                Thread.sleep(pollIntervalMs);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                throw new AnalysisException("Interrupted while polling job: " + jobId, ie);
            }
        }

        throw new RuntimeException(
                "Job " + jobId + " did not complete within the maximum wait time. " +
                "The Python service may still be running. Check job_store/" + jobId + "/status.json"
        );
    }

    public AnalysisResponse getResult(String jobId) throws AnalysisException {
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
            Map<?, ?> body = gson.fromJson(response.body(), Map.class);
            Object statusObj = body.get("status");
            if (statusObj != null && "failed".equalsIgnoreCase(statusObj.toString())) {
                throw new AnalysisException(getFailedMessageFromBody(jobId, body));
            }

            Object resultObj = body.get("result");
            if (resultObj == null) {
                // In phase1_only mode, Python won't have a result payload.
                // We return a skeleton response so the orchestrator can continue to Phase 2.
                return new AnalysisResponse();
            }
            // Re-serialize resultObj back to JSON string to parse as AnalysisResponse.
            String resultJson = gson.toJson(resultObj);
            return gson.fromJson(resultJson, AnalysisResponse.class);
        } catch (Exception e) {
            throw new AnalysisException("Failed to fetch result for job: " + jobId + " (" + e.getMessage() + ")", e);
        }
    }

    public JobStatus getJobStatus(String jobId) throws AnalysisException {
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

            Map<?, ?> body = gson.fromJson(response.body(), Map.class);
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

    private String getFailedJobMessage(String jobId, String fallback) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + RESULT_ENDPOINT_PREFIX + jobId))
                    .header("Content-Type", "application/json")
                    .timeout(DEFAULT_TIMEOUT)
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                return fallback == null ? "Job failed." : fallback;
            }

            Map<?, ?> body = gson.fromJson(response.body(), Map.class);
            return getFailedMessageFromBody(jobId, body);
        } catch (Exception e) {
            return fallback == null ? "Job failed." : fallback;
        }
    }

    private String getFailedMessageFromBody(String jobId, Map<?, ?> body) {
        Object errorObj = body.get("error");
        if (errorObj instanceof Map<?, ?> errorMap) {
            String message = errorMap.get("message") == null ? "Job failed." : errorMap.get("message").toString();
            String failedPhase = errorMap.get("failed_phase") == null ? "unknown" : errorMap.get("failed_phase").toString();
            boolean phase1Artifacts = Boolean.parseBoolean(String.valueOf(errorMap.get("phase1_artifacts_available")));
            return "Job " + jobId + " failed in " + failedPhase + ": " + message
                    + " (phase1_artifacts_available=" + phase1Artifacts + ")";
        }
        return "Job " + jobId + " failed.";
    }

    public static class JobStatus {
        public String jobId;
        public String status;
        public double progress;
        public String message;
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
