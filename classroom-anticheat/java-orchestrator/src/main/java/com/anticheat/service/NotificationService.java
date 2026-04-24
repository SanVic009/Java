package com.anticheat.service;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.NotificationConfig;
import com.anticheat.model.ViolationEvent;
import jakarta.mail.Authenticator;
import jakarta.mail.Message;
import jakarta.mail.MessagingException;
import jakarta.mail.Multipart;
import jakarta.mail.PasswordAuthentication;
import jakarta.mail.Session;
import jakarta.mail.Transport;
import jakarta.mail.internet.InternetAddress;
import jakarta.mail.internet.MimeBodyPart;
import jakarta.mail.internet.MimeMessage;
import jakarta.mail.internet.MimeMultipart;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import java.util.Properties;
import java.util.stream.Collectors;

public class NotificationService {

    private final String smtpHost;
    private final int smtpPort;
    private final String smtpUser;
    private final String smtpPass;
    private final String fromAddress;
    private final List<String> recipients;
    private final String cvServiceBaseUrl;
    private final boolean useTls;

    public NotificationService(NotificationConfig config, String cvServiceBaseUrl) {
        this.smtpHost = firstNonBlankEnv(config.smtp.hostEnv, "SMTP_HOST", "MAIL_HOST", "smtp.gmail.com");
        String portRaw = firstNonBlankEnv(config.smtp.portEnv, "SMTP_PORT", "MAIL_PORT", "587");
        this.smtpPort = Integer.parseInt(portRaw);
        this.smtpUser = firstNonBlankEnv(config.smtp.usernameEnv, "SMTP_USERNAME", "SMTP_USER", null);
        this.smtpPass = firstNonBlankEnv(config.smtp.passwordEnv, "SMTP_PASSWORD", "SMTP_PASS", null);
        this.fromAddress = resolveFromAddress(config);
        this.recipients = resolveRecipients(config);
        this.cvServiceBaseUrl = cvServiceBaseUrl;
        this.useTls = config.smtp.useTls;
    }

    private String resolveFromAddress(NotificationConfig config) {
        if (config.smtp == null) {
            return null;
        }

        String envName = config.smtp.fromAddressEnv;
        if (envName != null && !envName.isBlank()) {
            String envValue = readEnvOrProperty(envName);
            if (envValue != null && !envValue.isBlank()) {
                return envValue.trim();
            }
        }

        String fallbackEnv = readEnvOrProperty("SMTP_FROM_ADDRESS");
        if (fallbackEnv != null && !fallbackEnv.isBlank()) {
            return fallbackEnv.trim();
        }

        if (config.smtp.fromAddress != null && !config.smtp.fromAddress.isBlank()) {
            return config.smtp.fromAddress.trim();
        }

        if (smtpUser != null && !smtpUser.isBlank()) {
            return smtpUser.trim();
        }

        return null;
    }

    private List<String> resolveRecipients(NotificationConfig config) {
        if (config.smtp != null && config.smtp.recipientsEnv != null && !config.smtp.recipientsEnv.isBlank()) {
            String raw = readEnvOrProperty(config.smtp.recipientsEnv);
            if (raw != null && !raw.isBlank()) {
                return Arrays.stream(raw.split(","))
                        .map(String::trim)
                        .filter(s -> !s.isBlank())
                        .collect(Collectors.toList());
            }
        }

        String rawFallback = readEnvOrProperty("ALERT_RECIPIENTS");
        if (rawFallback != null && !rawFallback.isBlank()) {
            return Arrays.stream(rawFallback.split(","))
                    .map(String::trim)
                    .filter(s -> !s.isBlank())
                    .collect(Collectors.toList());
        }

        return config.recipients == null ? List.of() : config.recipients;
    }

    private String firstNonBlankEnv(String preferredEnvName, String fallback1, String fallback2, String defaultValue) {
        String[] candidates = new String[]{preferredEnvName, fallback1, fallback2};
        for (String c : candidates) {
            if (c == null || c.isBlank()) {
                continue;
            }
            String v = readEnvOrProperty(c);
            if (v != null && !v.isBlank()) {
                return v.trim();
            }
        }
        return defaultValue;
    }

    private String readEnvOrProperty(String key) {
        String fromEnv = System.getenv(key);
        if (fromEnv != null && !fromEnv.isBlank()) {
            return fromEnv;
        }
        return System.getProperty(key);
    }

    /**
     * Called immediately after job completes.
     * Sends one email per high-confidence violation interval.
     */
    public void sendImmediateAlerts(String jobId, String examId, AnalysisResponse response) {
        List<ViolationEvent> events = extractViolationEvents(jobId, examId, response);
        if (events.isEmpty()) {
            System.out.println("[Notification] No high-confidence violations to report.");
            return;
        }
        if (smtpUser == null || smtpUser.isBlank() || smtpPass == null || smtpPass.isBlank()) {
            System.out.println("[Notification] SMTP credentials not configured; expected SMTP_USERNAME/SMTP_PASSWORD or SMTP_USER/SMTP_PASS.");
            return;
        }
        if (fromAddress == null || fromAddress.isBlank()) {
            System.out.println("[Notification] Sender address not configured; skipping alerts.");
            return;
        }
        if (recipients.isEmpty()) {
            System.out.println("[Notification] No recipients configured; skipping alerts.");
            return;
        }

        try {
            sendViolationSummaryEmail(events, examId);
            System.out.printf("[Notification] Consolidated alert sent for %d violations%n", events.size());
        } catch (Exception e) {
            System.err.printf("[Notification] Failed to send consolidated alert: %s%n", e.getMessage());
        }
    }

    private List<ViolationEvent> extractViolationEvents(
            String jobId, String examId, AnalysisResponse response) {
        List<ViolationEvent> events = new ArrayList<>();
        if (response == null || response.getResults() == null) {
            return events;
        }

        for (var track : response.getResults()) {
            if (track.getIntervals() == null) {
                continue;
            }
            for (var interval : track.getIntervals()) {
                ViolationEvent event = new ViolationEvent();
                event.examId = examId;
                event.jobId = jobId;
                event.trackId = track.getTrackId();
                event.startSec = interval.getStart();
                event.endSec = interval.getEnd();
                event.durationSec = interval.getDuration();
                event.peakScore = interval.getPeakScore();
                event.dominantSignals = interval.getDominantSignals();
                event.clipPath = String.format(
                        "job_store/%s/snapshots/track_%d_t%.1f.mp4",
                        jobId, event.trackId, event.startSec
                );
                event.clipUrl = String.format(
                        "%s/static/%s/snapshots/track_%d_t%.1f.mp4",
                        cvServiceBaseUrl, jobId, event.trackId, event.startSec
                );
                event.detectedAt = Instant.now().toString();
                events.add(event);
            }
        }
        return events;
    }

    private void sendViolationSummaryEmail(List<ViolationEvent> events, String examId) throws MessagingException {
        Properties props = new Properties();
        props.put("mail.smtp.auth", "true");
        props.put("mail.smtp.starttls.enable", Boolean.toString(useTls));
        props.put("mail.smtp.host", smtpHost);
        props.put("mail.smtp.port", Integer.toString(smtpPort));

        Session session = Session.getInstance(props, new Authenticator() {
            protected PasswordAuthentication getPasswordAuthentication() {
                return new PasswordAuthentication(smtpUser, smtpPass);
            }
        });

        Message message = new MimeMessage(session);
        message.setFrom(new InternetAddress(fromAddress));
        for (String recipient : recipients) {
            message.addRecipient(Message.RecipientType.TO, new InternetAddress(recipient));
        }

        message.setSubject(String.format(
                "[Anti-Cheat Alert] Exam %s — %d Violations Detected",
                examId, events.size()
        ));

        Multipart multipart = new MimeMultipart();

        MimeBodyPart htmlPart = new MimeBodyPart();
        htmlPart.setContent(buildSummaryEmailBody(events, examId), "text/html; charset=utf-8");
        multipart.addBodyPart(htmlPart);

        Optional<String> jobId = events.stream()
                .map(e -> e.jobId)
                .filter(s -> s != null && !s.isBlank())
                .findFirst();
        if (jobId.isPresent()) {
            Optional<Path> annotatedVideoPath = resolveAnnotatedVideoPath(jobId.get());
            if (annotatedVideoPath.isPresent()) {
                MimeBodyPart attachment = new MimeBodyPart();
                try {
                    attachment.attachFile(annotatedVideoPath.get().toFile());
                    attachment.setFileName(annotatedVideoPath.get().getFileName().toString());
                    attachment.setDisposition(Message.ATTACHMENT);
                    multipart.addBodyPart(attachment);
                } catch (IOException e) {
                    throw new MessagingException("Failed to attach annotated video", e);
                }
            } else {
                System.out.printf("[Notification] Annotated video not found for job %s; sending email without attachment.%n", jobId.get());
            }
        }

        message.setContent(multipart);
        Transport.send(message);
    }

    private Optional<Path> resolveAnnotatedVideoPath(String jobId) {
        Path cwd = Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();
        Path cwdJobStore = cwd.resolve("job_store");
        Path nestedRepoJobStore = cwd.resolve("classroom-anticheat").resolve("job_store");
        Path parent = cwd.getParent();
        Path parentJobStore = parent == null ? null : parent.resolve("job_store");

        Path jobStoreRoot;
        if (cwd.getFileName() != null
                && "java-orchestrator".equals(cwd.getFileName().toString())
                && parentJobStore != null
                && Files.isDirectory(parentJobStore)) {
            jobStoreRoot = parentJobStore;
        } else if (Files.isDirectory(nestedRepoJobStore)) {
            // Launching from workspace root (/.../Code/Java) while artifacts are under
            // /.../Code/Java/classroom-anticheat/job_store.
            jobStoreRoot = nestedRepoJobStore;
        } else if (Files.isDirectory(cwdJobStore)) {
            jobStoreRoot = cwdJobStore;
        } else if (parentJobStore != null && Files.isDirectory(parentJobStore)) {
            jobStoreRoot = parentJobStore;
        } else {
            jobStoreRoot = cwdJobStore;
        }

        Path jobDir = jobStoreRoot.resolve(jobId);
        Path pyAnnotated = jobDir.resolve("phase2_annotated.mp4");
        if (Files.exists(pyAnnotated) && Files.isRegularFile(pyAnnotated)) {
            return Optional.of(pyAnnotated);
        }

        Path javaAnnotated = jobDir.resolve("phase2_annotated_java.mp4");
        if (Files.exists(javaAnnotated) && Files.isRegularFile(javaAnnotated)) {
            return Optional.of(javaAnnotated);
        }

        return Optional.empty();
    }

    private String buildSummaryEmailBody(List<ViolationEvent> events, String examId) {
        StringBuilder sb = new StringBuilder();
        sb.append("<html><body style='font-family: sans-serif;'>");
        sb.append("<h2 style='color: #d9534f;'>Classroom Anti-Cheat System</h2>");
        sb.append("<p>The system has detected potential violations. Please review the details below:</p>");
        sb.append("<p><b>Annotated video is attached to this email.</b></p>");
        sb.append("<ul>");
        sb.append(String.format("<li><b>Exam ID:</b> %s</li>", examId));
        sb.append(String.format("<li><b>Total Violations:</b> %d</li>", events.size()));
        sb.append("</ul><hr/>");
        
        for (ViolationEvent event : events) {
            String dominant = event.dominantSignals == null || event.dominantSignals.isEmpty() ? "None" : String.join(", ", event.dominantSignals);
            sb.append("<div style='margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 5px; background: #f9f9f9;'>");
            sb.append(String.format("<h3 style='margin-top: 0;'>Track ID: %d</h3>", event.trackId));
            sb.append("<ul>");
            sb.append(String.format("<li><b>Time Window:</b> %.1f s &mdash; %.1f s (Duration: %.1f s)</li>", event.startSec, event.endSec, event.durationSec));
            sb.append(String.format("<li><b>Dominant Signals:</b> %s</li>", dominant));
            sb.append(String.format("<li><b>Detected At:</b> %s</li>", event.detectedAt));
            sb.append("</ul>");
            sb.append("</div>");
        }
        
        sb.append("<p style='font-size: 0.9em; color: #777;'>This is an automated alert. Please do not reply to this email.</p>");
        sb.append("</body></html>");
        return sb.toString();
    }
}
