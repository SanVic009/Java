package com.anticheat.model;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.annotations.SerializedName;

import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public class NotificationConfig {
    private static final String RESOURCE_NAME = "notification_config.json";

    public boolean enabled = false;

    @SerializedName("delivery_mode")
    public String deliveryMode = "immediate";

    @SerializedName("peak_score_threshold")
    public double peakScoreThreshold = 0.35;

    public List<String> recipients = new ArrayList<>();

    public SmtpConfig smtp = new SmtpConfig();

    public DigestConfig digest = new DigestConfig();

    public static NotificationConfig load() {
        Gson gson = new GsonBuilder().create();
        ClassLoader classLoader = NotificationConfig.class.getClassLoader();
        try (InputStream stream = classLoader.getResourceAsStream(RESOURCE_NAME)) {
            if (stream == null) {
                return new NotificationConfig();
            }
            try (InputStreamReader reader = new InputStreamReader(stream, StandardCharsets.UTF_8)) {
                NotificationConfig cfg = gson.fromJson(reader, NotificationConfig.class);
                return cfg == null ? new NotificationConfig() : cfg;
            }
        } catch (Exception e) {
            throw new IllegalStateException("Failed to load " + RESOURCE_NAME + ": " + e.getMessage(), e);
        }
    }

    public static class SmtpConfig {
        @SerializedName("host_env")
        public String hostEnv;

        @SerializedName("port_env")
        public String portEnv;

        @SerializedName("username_env")
        public String usernameEnv;

        @SerializedName("password_env")
        public String passwordEnv;

        @SerializedName("from_address_env")
        public String fromAddressEnv;

        @SerializedName("from_address")
        public String fromAddress;

        @SerializedName("recipients_env")
        public String recipientsEnv;

        @SerializedName("use_tls")
        public boolean useTls = true;
    }

    public static class DigestConfig {
        @SerializedName("schedule_cron")
        public String scheduleCron;

        @SerializedName("max_events_per_digest")
        public int maxEventsPerDigest = 50;
    }
}
