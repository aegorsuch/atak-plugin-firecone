package com.atakmap.android.firecone.plugin;

import android.content.Context;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

import com.atakmap.android.maps.MapEvent;
import com.atakmap.android.maps.MapEventDispatcher;
import com.atakmap.android.maps.MapItem;
import com.atakmap.android.maps.MapView;
import com.atakmap.android.maps.Marker;
import com.atakmap.android.maps.PointMapItem;
import com.atakmap.android.maps.SensorFOV;
import com.atakmap.coremap.maps.coords.GeoPoint;
import com.atakmap.coremap.maps.coords.GeoPointMetaData;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

final class FireconeOverlay implements PointMapItem.OnPointChangedListener,
        Marker.OnTrackChangedListener, MapItem.OnVisibleChangedListener,
        MapItem.OnMetadataChangedListener, Marker.OnIconChangedListener,
        MapEventDispatcher.MapEventDispatchListener {

    interface StatusListener {
        void onStatus(String text);
    }

    private static final int CONE_WIDTH_DEGREES = 60;
    private static final int CONE_RANGE_METERS = 50;
    private static final long HEADING_TIMEOUT_MILLIS = 30_000;
    private static final int STOPPED_FILL = Color.argb(60, 140, 140, 140);
    private static final int STOPPED_STROKE = Color.rgb(160, 160, 160);

    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Map<Marker, SensorFOV> cones = new HashMap<>();
    private final HeadingTracker<Marker> headings = new HeadingTracker<>();
    private final Runnable expireHeadings = () -> {
        for (Marker marker : new ArrayList<>(cones.keySet()))
            update(marker, false);
    };
    private StatusListener statusListener;
    private MapView map;

    FireconeOverlay(Context context) {
        this.context = context;
    }

    void setStatusListener(StatusListener listener) {
        statusListener = listener;
    }

    boolean isRunning() {
        return map != null;
    }

    boolean start() {
        if (map == null) {
            map = MapView.getMapView();
            if (map == null) {
                status(context.getString(R.string.cone_no_map));
                return false;
            }
            map.getMapEventDispatcher().addMapEventListener(MapEvent.ITEM_ADDED, this);
            map.getMapEventDispatcher().addMapEventListener(MapEvent.ITEM_REMOVED, this);
            for (MapItem item : map.getRootGroup().getItemsRecursive())
                watch(item);
        }
        for (Marker marker : cones.keySet())
            update(marker, false);
        updateStatus();
        return true;
    }

    void stop() {
        main.removeCallbacks(expireHeadings);
        if (map != null) {
            map.getMapEventDispatcher().removeMapEventListener(MapEvent.ITEM_ADDED, this);
            map.getMapEventDispatcher().removeMapEventListener(MapEvent.ITEM_REMOVED, this);
        }
        for (Map.Entry<Marker, SensorFOV> entry : cones.entrySet()) {
            Marker marker = entry.getKey();
            marker.removeOnPointChangedListener(this);
            marker.removeOnTrackChangedListener(this);
            marker.removeOnVisibleChangedListener(this);
            marker.removeOnIconChangedListener(this);
            marker.removeOnMetadataChangedListener("stale", this);
            marker.removeOnMetadataChangedListener("forceStale", this);
            marker.removeOnMetadataChangedListener("teamColor", this);
            entry.getValue().removeFromGroup();
        }
        cones.clear();
        headings.clear();
        map = null;
        status(context.getString(R.string.cone_stopped));
    }

    @Override
    public void onMapEvent(MapEvent event) {
        MapItem item = event.getItem();
        String type = event.getType();
        main.post(() -> {
            if (map == null)
                return;
            if (MapEvent.ITEM_ADDED.equals(type))
                watch(item);
            else if (MapEvent.ITEM_REMOVED.equals(type) && item instanceof Marker)
                unwatch((Marker) item);
        });
    }

    @Override
    public void onPointChanged(PointMapItem item) {
        main.post(() -> update((Marker) item, true));
    }

    @Override
    public void onTrackChanged(Marker marker) {
        main.post(() -> update(marker, true));
    }

    @Override
    public void onVisibleChanged(MapItem item) {
        main.post(() -> update((Marker) item, false));
    }

    @Override
    public void onMetadataChanged(MapItem item, String key) {
        main.post(() -> update((Marker) item, false));
    }

    @Override
    public void onIconChanged(Marker marker) {
        main.post(() -> update(marker, false));
    }

    private void watch(MapItem item) {
        if (!(item instanceof Marker) || item == map.getSelfMarker()
                || item.getType() == null || !item.getType().startsWith("a-f"))
            return;
        Marker marker = (Marker) item;
        if (cones.containsKey(marker))
            return;
        SensorFOV cone = new SensorFOV(UUID.randomUUID().toString());
        cone.setTitle(context.getString(R.string.app_name));
        cone.setVisible(false);
        cones.put(marker, cone);
        map.getRootGroup().addItem(cone);
        marker.addOnPointChangedListener(this);
        marker.addOnTrackChangedListener(this);
        marker.addOnVisibleChangedListener(this);
        marker.addOnIconChangedListener(this);
        marker.addOnMetadataChangedListener("stale", this);
        marker.addOnMetadataChangedListener("forceStale", this);
        marker.addOnMetadataChangedListener("teamColor", this);
        update(marker, true);
    }

    private void unwatch(Marker marker) {
        SensorFOV cone = cones.remove(marker);
        if (cone == null)
            return;
        marker.removeOnPointChangedListener(this);
        marker.removeOnTrackChangedListener(this);
        marker.removeOnVisibleChangedListener(this);
        marker.removeOnIconChangedListener(this);
        marker.removeOnMetadataChangedListener("stale", this);
        marker.removeOnMetadataChangedListener("forceStale", this);
        marker.removeOnMetadataChangedListener("teamColor", this);
        cone.removeFromGroup();
        headings.remove(marker);
        scheduleExpiry();
        updateStatus();
    }

    private void update(Marker marker, boolean observed) {
        SensorFOV cone = cones.get(marker);
        if (cone == null)
            return;
        GeoPointMetaData position = marker.getGeoPointMetaData();
        GeoPoint point = position != null ? position.get() : null;
        double heading = marker.getTrackHeading();
        double speed = marker.getTrackSpeed();
        boolean visible = marker.getVisible();
        boolean stale = marker.getMetaBoolean("stale", false);
        boolean forceStale = marker.getMetaBoolean("forceStale", false);
        boolean validPosition = point != null && point.isValid();
        HeadingTracker.Direction direction = headings.direction(marker, heading, speed,
                observed && visible && !stale && !forceStale && validPosition,
                SystemClock.elapsedRealtime(), HEADING_TIMEOUT_MILLIS);
        if (!HeadingTracker.canDisplay(visible, stale, forceStale, validPosition, direction)) {
            cone.setVisible(false);
        } else {
            int color = marker.getMetaInteger("teamColor", marker.getIconColor());
            cone.setFillColor(direction.moving
                    ? Color.argb(75, Color.red(color), Color.green(color), Color.blue(color))
                    : STOPPED_FILL);
            cone.setStrokeColor(direction.moving ? color | Color.BLACK : STOPPED_STROKE);
            cone.setPoint(position);
            cone.setMetrics(direction.heading, CONE_WIDTH_DEGREES, CONE_RANGE_METERS);
            cone.setVisible(true);
        }
        updateStatus();
        scheduleExpiry();
    }

    private void scheduleExpiry() {
        main.removeCallbacks(expireHeadings);
        if (map != null) {
            long delay = headings.nextExpiry(SystemClock.elapsedRealtime(), HEADING_TIMEOUT_MILLIS);
            if (delay != Long.MAX_VALUE)
                main.postDelayed(expireHeadings, delay);
        }
    }

    private void updateStatus() {
        int moving = 0;
        int stopped = 0;
        for (Map.Entry<Marker, SensorFOV> entry : cones.entrySet()) {
            if (entry.getValue().getVisible()) {
                double speed = entry.getKey().getTrackSpeed();
                double heading = entry.getKey().getTrackHeading();
                if (Double.isFinite(heading) && Double.isFinite(speed)
                        && speed >= HeadingTracker.MIN_SPEED_METERS_PER_SECOND)
                    moving++;
                else
                    stopped++;
            }
        }
        status(context.getString(R.string.cone_active, moving, stopped));
    }

    private void status(String text) {
        if (statusListener != null)
            statusListener.onStatus(text);
    }
}
