package com.atakmap.android.firecone.plugin;

import android.content.Context;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;

import com.atakmap.android.maps.MapEvent;
import com.atakmap.android.maps.MapEventDispatcher;
import com.atakmap.android.maps.MapItem;
import com.atakmap.android.maps.MapView;
import com.atakmap.android.maps.Marker;
import com.atakmap.android.maps.PointMapItem;
import com.atakmap.android.maps.SensorFOV;
import com.atakmap.coremap.maps.coords.GeoPoint;
import com.atakmap.coremap.maps.coords.GeoPointMetaData;

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

    private static final double MIN_SPEED_METERS_PER_SECOND = 0.5;
    private static final float CONE_WIDTH_DEGREES = 60f;
    private static final float CONE_RANGE_METERS = 500f;
    private static final int STOPPED_FILL = Color.argb(60, 140, 140, 140);
    private static final int STOPPED_STROKE = Color.rgb(160, 160, 160);

    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Map<Marker, SensorFOV> cones = new HashMap<>();
    private final Map<Marker, Float> lastMovingHeadings = new HashMap<>();
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
            update(marker);
        updateStatus();
        return true;
    }

    void stop() {
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
        lastMovingHeadings.clear();
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
        main.post(() -> update((Marker) item));
    }

    @Override
    public void onTrackChanged(Marker marker) {
        main.post(() -> update(marker));
    }

    @Override
    public void onVisibleChanged(MapItem item) {
        main.post(() -> update((Marker) item));
    }

    @Override
    public void onMetadataChanged(MapItem item, String key) {
        main.post(() -> update((Marker) item));
    }

    @Override
    public void onIconChanged(Marker marker) {
        main.post(() -> update(marker));
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
        update(marker);
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
        lastMovingHeadings.remove(marker);
        updateStatus();
    }

    private void update(Marker marker) {
        SensorFOV cone = cones.get(marker);
        if (cone == null)
            return;
        GeoPointMetaData position = marker.getGeoPointMetaData();
        GeoPoint point = position != null ? position.get() : null;
        double heading = marker.getTrackHeading();
        double speed = marker.getTrackSpeed();
        if (!marker.getVisible() || marker.getMetaBoolean("stale", false)
                || marker.getMetaBoolean("forceStale", false)
                || point == null || !point.isValid()) {
            cone.setVisible(false);
        } else {
            boolean moving = Double.isFinite(heading) && Double.isFinite(speed)
                    && speed >= MIN_SPEED_METERS_PER_SECOND;
            if (moving)
                lastMovingHeadings.put(marker, (float) heading);
            Float lastHeading = lastMovingHeadings.get(marker);
            if (lastHeading == null) {
                cone.setVisible(false);
            } else {
                int color = marker.getMetaInteger("teamColor", marker.getIconColor());
                cone.setFillColor(moving
                        ? Color.argb(75, Color.red(color), Color.green(color), Color.blue(color))
                        : STOPPED_FILL);
                cone.setStrokeColor(moving ? color | Color.BLACK : STOPPED_STROKE);
                cone.setPoint(position);
                cone.setMetrics(lastHeading, CONE_WIDTH_DEGREES, CONE_RANGE_METERS);
                cone.setVisible(true);
            }
        }
        updateStatus();
    }

    private void updateStatus() {
        int moving = 0;
        int stopped = 0;
        for (Map.Entry<Marker, SensorFOV> entry : cones.entrySet()) {
            if (entry.getValue().getVisible()) {
                double speed = entry.getKey().getTrackSpeed();
                if (Double.isFinite(speed) && speed >= MIN_SPEED_METERS_PER_SECOND)
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
