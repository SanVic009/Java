package com.anticheat.util;

import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/**
 * Loads key=value pairs from a .env file into the process environment.
 *
 * Supports:
 *   - Lines with or without the "export " prefix
 *   - Quoted values (single or double quotes, stripped)
 *   - Inline comments (# after the value)
 *   - Blank lines and comment-only lines (skipped)
 *
 * Variables already set in the real OS environment are NOT overwritten,
 * so real env vars always take precedence over .env.
 */
public class DotEnvLoader {

    private DotEnvLoader() {}

    /**
     * Search for a .env file in the given directory and its parent, then load it.
     * Silently does nothing if no .env file is found.
     *
     * @param searchDir directory to start searching from (e.g. Paths.get(user.dir))
     */
    public static void loadFromDirectory(Path searchDir) {
        Path[] candidates = {
            searchDir.resolve(".env"),
            searchDir.getParent() != null ? searchDir.getParent().resolve(".env") : null,
        };
        for (Path candidate : candidates) {
            if (candidate != null && Files.isRegularFile(candidate)) {
                loadFile(candidate);
                return;
            }
        }
    }

    /**
     * Load a specific .env file and inject its variables into the JVM environment.
     */
    public static void loadFile(Path envFile) {
        Map<String, String> vars = new HashMap<>();
        try {
            for (String rawLine : Files.readAllLines(envFile)) {
                String line = rawLine.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;

                // Strip leading "export " if present
                if (line.startsWith("export ")) {
                    line = line.substring(7).trim();
                }

                int eqIdx = line.indexOf('=');
                if (eqIdx <= 0) continue;

                String key   = line.substring(0, eqIdx).trim();
                String value = line.substring(eqIdx + 1).trim();

                value = stripInlineComment(value);
                value = stripQuotes(value);

                // Real OS env vars take precedence — do not overwrite
                if (System.getenv(key) == null) {
                    vars.put(key, value);
                }
            }

            if (!vars.isEmpty()) {
                injectIntoEnvironment(vars);
                System.out.printf("[DotEnvLoader] Loaded %d variable(s) from %s%n", vars.size(), envFile);
            }

        } catch (IOException e) {
            System.err.println("[DotEnvLoader] Warning: could not read " + envFile + ": " + e.getMessage());
        }
    }

    // Convenience alias used by Main.java
    public static void load(Path searchDir) {
        loadFromDirectory(searchDir);
    }

    // -------------------------------------------------------------------------

    private static String stripInlineComment(String value) {
        boolean inSingle = false, inDouble = false;
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if      (c == '\'' && !inDouble) inSingle = !inSingle;
            else if (c == '"'  && !inSingle) inDouble = !inDouble;
            else if (c == '#'  && !inSingle && !inDouble) {
                return value.substring(0, i).trim();
            }
        }
        return value;
    }

    private static String stripQuotes(String value) {
        if ((value.startsWith("\"") && value.endsWith("\"")) ||
            (value.startsWith("'")  && value.endsWith("'"))) {
            return value.substring(1, value.length() - 1);
        }
        return value;
    }

    /**
     * Injects variables into the JVM's live environment map via reflection.
     * Java has no public setenv() API, so this is the standard approach.
     * Works on OpenJDK 8–21.
     */
    @SuppressWarnings({"unchecked"})
    private static void injectIntoEnvironment(Map<String, String> vars) {
        try {
            Class<?> envClass = Class.forName("java.lang.ProcessEnvironment");

            // theCaseInsensitiveEnvironment is the String→String map on all platforms
            Field ciField = envClass.getDeclaredField("theCaseInsensitiveEnvironment");
            ciField.setAccessible(true);
            Map<String, String> ciEnv = (Map<String, String>) ciField.get(null);
            ciEnv.putAll(vars);

            // theEnvironment holds the raw backing map (Linux/Mac)
            try {
                Field rawField = envClass.getDeclaredField("theEnvironment");
                rawField.setAccessible(true);
                Map<Object, Object> rawEnv = (Map<Object, Object>) rawField.get(null);
                rawEnv.putAll(vars);
            } catch (NoSuchFieldException ignored) {
                // Windows doesn't have theEnvironment — ciEnv is sufficient
            }

        } catch (Exception e) {
            System.err.println("[DotEnvLoader] Warning: reflection injection failed: " + e.getMessage());
            System.err.println("[DotEnvLoader] Fallback: run 'source java-orchestrator/.env' before launching.");
        }
    }
}
