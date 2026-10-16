package com.atakmap.android.firecone.plugin;

import java.util.HashMap;
import java.util.Map;

final class HeadingTracker<T> {
    static final double MIN_SPEED_METERS_PER_SECOND = 0.5;

    static final class Direction {
        final float heading;
        final boolean moving;

        Direction(float heading, boolean moving) {
            this.heading = heading;
            this.moving = moving;
        }
    }

    private static final class Observation {
        final float heading;
        final long time;

        Observation(float heading, long time) {
            this.heading = heading;
            this.time = time;
        }
    }

    private final Map<T, Observation> observations = new HashMap<>();

    Direction direction(T item, double heading, double speed, boolean observed,
                        long now, long timeoutMillis) {
        boolean moving = Double.isFinite(heading) && Double.isFinite(speed)
                && speed >= MIN_SPEED_METERS_PER_SECOND;
        if (observed && moving)
            observations.put(item, new Observation((float) heading, now));

        Observation last = observations.get(item);
        if (last == null)
            return null;
        if (now - last.time >= timeoutMillis) {
            observations.remove(item);
            return null;
        }
        return new Direction(last.heading, moving);
    }

    long nextExpiry(long now, long timeoutMillis) {
        long delay = Long.MAX_VALUE;
        for (Observation observation : observations.values())
            delay = Math.min(delay, Math.max(0, timeoutMillis - (now - observation.time)));
        return delay;
    }

    static boolean canDisplay(boolean visible, boolean stale, boolean forceStale,
                              boolean validPosition, Direction direction) {
        return visible && !stale && !forceStale && validPosition && direction != null;
    }

    void remove(T item) {
        observations.remove(item);
    }

    void clear() {
        observations.clear();
    }
}
