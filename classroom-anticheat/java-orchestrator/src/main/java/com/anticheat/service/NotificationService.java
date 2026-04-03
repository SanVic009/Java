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
        this.smtpHost = System.getenv(config.smtp.hostEnv);
        this.smtpPort = Integer.parseInt(
                Optional.ofNullable(System.getenv(config.smtp.portEnv)).orElse("587")
        );
        this.smtpUser = System.getenv(config.smtp.usernameEnv);
        this.smtpPass = System.getenv(config.smtp.passwordEnv);
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
            String envValue = System.getenv(envName);
            if (envValue != null && !envValue.isBlank()) {
                return envValue.trim();
            }
        }

        if (config.smtp.fromAddress != null && !config.smtp.fromAddress.isBlank()) {
            return config.smtp.fromAddress.trim();
        }

        return null;
    }

    private List<String> resolveRecipients(NotificationConfig config) {
        if (config.smtp != null && config.smtp.recipientsEnv != null && !config.smtp.recipientsEnv.isBlank()) {
            String raw = System.getenv(config.smtp.recipientsEnv);
            if (raw != null && !raw.isBlank()) {
                return Arrays.stream(raw.split(","))
                        .map(String::trim)
                        .filter(s -> !s.isBlank())
                        .collect(Collectors.toList());
            }
        }

        return config.recipients == null ? List.of() : config.recipients;
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
        if (fromAddress == null || fromAddress.isBlank()) {
            System.out.println("[Notification] Sender address not configured; skipping alerts.");
            return;
        }
        if (recipients.isEmpty()) {
            System.out.println("[Notification] No recipients configured; skipping alerts.");
            return;
        }

        for (ViolationEvent event : events) {
            try {
                sendViolationEmail(event);
                System.out.printf("[Notification] Alert sent for track %d (%.2f–%.2fs)%n",
                        event.trackId, event.startSec, event.endSec);
            } catch (Exception e) {
                System.err.printf("[Notification] Failed to send alert for track %d: %s%n",
                        event.trackId, e.getMessage());
                // Do NOT rethrow — notification failure must not fail the overall job.
            }
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

    private void sendViolationEmail(ViolationEvent event) throws MessagingException {
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
                "[Anti-Cheat Alert] Exam %s — Track %d flagged (score: %.2f)",
                event.examId, event.trackId, event.peakScore
        ));

        Multipart multipart = new MimeMultipart();

        MimeBodyPart textPart = new MimeBodyPart();
        textPart.setText(buildEmailBody(event), "utf-8", "plain");
        multipart.addBodyPart(textPart);

        message.setContent(multipart);
        Transport.send(message);
    }

    private String buildEmailBody(ViolationEvent event) {
        String dominant = event.dominantSignals == null ? "" : String.join(", ", event.dominantSignals);
        return String.format("""
                CHEATING VIOLATION DETECTED
                ============================
                Exam ID:          %s
                Track ID:         %d
                Time window:      %.1f s — %.1f s (duration: %.1f s)
                Peak score:       %.3f
                Dominant signals: %s
                Detected at:      %s

                Clip URL: %s

                This is an automated alert from the Classroom Anti-Cheat System.
                """,
                event.examId, event.trackId,
                event.startSec, event.endSec, event.durationSec,
                event.peakScore,
                dominant,
                event.detectedAt,
                event.clipUrl
        );
    }
}
