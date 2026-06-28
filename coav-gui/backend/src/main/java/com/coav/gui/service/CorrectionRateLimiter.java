package com.coav.gui.service;

import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Sliding-window rate limiter: max MAX_REQUESTS per WINDOW_SECONDS per IP.
 * In-memory only — resets on restart, sufficient for PoC.
 * Production replacement: Redis + Lua atomic script.
 */
@Component
public class CorrectionRateLimiter {

    private static final int MAX_REQUESTS    = 10;
    private static final int WINDOW_SECONDS  = 60;

    private final ConcurrentHashMap<String, Deque<Instant>> windows = new ConcurrentHashMap<>();

    /** @return true if the request is allowed, false if rate limit exceeded */
    public synchronized boolean allow(String ip) {
        Instant now    = Instant.now();
        Instant cutoff = now.minusSeconds(WINDOW_SECONDS);

        Deque<Instant> hits = windows.computeIfAbsent(ip, k -> new ArrayDeque<>());

        // drop timestamps outside the sliding window
        while (!hits.isEmpty() && hits.peekFirst().isBefore(cutoff)) {
            hits.pollFirst();
        }

        if (hits.size() >= MAX_REQUESTS) {
            return false;
        }

        hits.addLast(now);
        return true;
    }
}
