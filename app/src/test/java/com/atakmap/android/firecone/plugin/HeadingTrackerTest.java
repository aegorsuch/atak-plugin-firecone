package com.atakmap.android.firecone.plugin;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class HeadingTrackerTest {
    private final HeadingTracker<String> headings = new HeadingTracker<>();
    private static final long TIMEOUT = 30_000;

    @Test
    public void movingHeadingExpiresWithoutAnotherReport() {
        HeadingTracker.Direction direction = headings.direction("friend", 45, 2, true, 100, TIMEOUT);
        assertEquals(45f, direction.heading, 0f);
        assertTrue(direction.moving);
        assertEquals(TIMEOUT, headings.nextExpiry(100, TIMEOUT));
        assertNull(headings.direction("friend", 45, 2, false, 100 + TIMEOUT, TIMEOUT));
        assertEquals(Long.MAX_VALUE, headings.nextExpiry(100 + TIMEOUT, TIMEOUT));
    }

    @Test
    public void stoppedHeadingIsHistoricalAndExpires() {
        headings.direction("friend", 70, 3, true, 100, TIMEOUT);
        HeadingTracker.Direction stopped = headings.direction("friend", Double.NaN, 0,
                true, 200, TIMEOUT);
        assertEquals(70f, stopped.heading, 0f);
        assertFalse(stopped.moving);
        assertNull(headings.direction("friend", Double.NaN, 0, false, 100 + TIMEOUT, TIMEOUT));
    }

    @Test
    public void noObservedMovingCourseMeansNoCone() {
        assertNull(headings.direction("friend", Double.NaN, 2, true, 0, TIMEOUT));
        assertNull(headings.direction("friend", 30, Double.NaN, true, 0, TIMEOUT));
        assertNull(headings.direction("friend", 30, 0.4, true, 0, TIMEOUT));
        assertNull(headings.direction("friend", 30, 2, false, 0, TIMEOUT));
    }

    @Test
    public void removalForgetsHeadingEvenIfMarkerReturns() {
        headings.direction("friend", 90, 2, true, 0, TIMEOUT);
        headings.remove("friend");
        assertNull(headings.direction("friend", 90, 0, false, 1, TIMEOUT));
        assertEquals(Long.MAX_VALUE, headings.nextExpiry(1, TIMEOUT));
    }

    @Test
    public void staleHiddenOrInvalidContactsDoNotDisplay() {
        HeadingTracker.Direction direction = headings.direction("friend", 90, 2,
                true, 0, TIMEOUT);
        assertTrue(HeadingTracker.canDisplay(true, false, false, true, direction));
        assertFalse(HeadingTracker.canDisplay(true, true, false, true, direction));
        assertFalse(HeadingTracker.canDisplay(true, false, true, true, direction));
        assertFalse(HeadingTracker.canDisplay(false, false, false, true, direction));
        assertFalse(HeadingTracker.canDisplay(true, false, false, false, direction));
        assertFalse(HeadingTracker.canDisplay(true, false, false, true, null));
    }

    @Test
    public void newReportsRefreshExpiryButOtherChangesDoNot() {
        headings.direction("friend", 90, 2, true, 0, TIMEOUT);
        headings.direction("friend", 90, 2, false, 1000, TIMEOUT);
        assertEquals(TIMEOUT - 1000, headings.nextExpiry(1000, TIMEOUT));
        headings.direction("friend", 100, 2, true, 2000, TIMEOUT);
        assertEquals(TIMEOUT, headings.nextExpiry(2000, TIMEOUT));
        headings.clear();
        assertNull(headings.direction("friend", 100, 0, false, 2001, TIMEOUT));
    }
}
