package com.anticheat.postcv;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;

final class ToolPaths {
    private ToolPaths() {}

    static String resolveBinary(String name) throws IOException, InterruptedException {
        List<String> candidates = new ArrayList<>();

        String env = System.getenv(name.toUpperCase() + "_BINARY");
        if (env != null && !env.isBlank()) candidates.add(env);

        if ("ffmpeg".equals(name)) {
            candidates.add("/usr/bin/ffmpeg");
        }
        if ("ffprobe".equals(name)) {
            candidates.add("/usr/bin/ffprobe");
        }

        candidates.add(name);

        LinkedHashSet<String> unique = new LinkedHashSet<>(candidates);
        for (String c : unique) {
            if (isRunnable(c, name.equals("ffprobe") ? "-version" : "-version")) {
                return c;
            }
        }
        throw new IOException("No usable binary found for " + name);
    }

    private static boolean isRunnable(String cmd, String arg) {
        try {
            Process p = new ProcessBuilder(cmd, arg).start();
            int code = p.waitFor();
            return code == 0;
        } catch (Exception ignored) {
            return false;
        }
    }
}
