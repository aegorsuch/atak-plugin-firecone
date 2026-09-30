
package com.atakmap.android.firecone.plugin;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Switch;
import android.widget.TextView;

import com.atak.plugins.impl.PluginContextProvider;
import com.atak.plugins.impl.PluginLayoutInflater;

import gov.tak.api.plugin.IPlugin;
import gov.tak.api.plugin.IServiceController;
import gov.tak.api.ui.IHostUIService;
import gov.tak.api.ui.Pane;
import gov.tak.api.ui.PaneBuilder;
import gov.tak.api.ui.ToolbarItem;
import gov.tak.api.ui.ToolbarItemAdapter;
import gov.tak.platform.marshal.MarshalManager;

public class FireconePlugin implements IPlugin {

    IServiceController serviceController;
    Context pluginContext;
    IHostUIService uiService;
    ToolbarItem toolbarItem;
    Pane conePane;
    FireconeOverlay overlay;
    Switch coneToggle;

    public FireconePlugin(IServiceController serviceController) {
        this.serviceController = serviceController;
        final PluginContextProvider ctxProvider = serviceController
                .getService(PluginContextProvider.class);
        if (ctxProvider != null) {
            pluginContext = ctxProvider.getPluginContext();
            pluginContext.setTheme(R.style.ATAKPluginTheme);
        }
        overlay = new FireconeOverlay(pluginContext);

        // obtain the UI service
        uiService = serviceController.getService(IHostUIService.class);

        // initialize the toolbar button for the plugin

        // create the button and set the identifier to be well known
        // if you fail to do this, the toolbar configuration will never
        // be able to find it again after the user moves the icon.
        toolbarItem = new ToolbarItem.Builder(
                pluginContext.getString(R.string.app_name),
                MarshalManager.marshal(
                        pluginContext.getResources().getDrawable(R.drawable.ic_launcher),
                        android.graphics.drawable.Drawable.class,
                        gov.tak.api.commons.graphics.Bitmap.class))
                .setListener(new ToolbarItemAdapter() {
                    @Override
                    public void onClick(ToolbarItem item) {
                        showPane();
                    }
                }).setIdentifier(pluginContext.getPackageName())
                .build();
    }

    @Override
    public void onStart() {
        // the plugin is starting, add the button to the toolbar
        if (uiService == null)
            return;

        uiService.addToolbarItem(toolbarItem);
    }

    @Override
    public void onStop() {
        new Handler(Looper.getMainLooper()).post(() -> {
            overlay.stop();
            if (coneToggle != null)
                coneToggle.setChecked(false);
        });
        if (uiService != null)
            uiService.removeToolbarItem(toolbarItem);
    }

    private void showPane() {
        if (conePane == null) {
            View view = PluginLayoutInflater.inflate(pluginContext, R.layout.main_layout, null);
            TextView status = view.findViewById(R.id.cone_status);
            coneToggle = view.findViewById(R.id.cone_toggle);
            overlay.setStatusListener(status::setText);
            coneToggle.setOnCheckedChangeListener((button, checked) -> {
                if (checked) {
                    if (!overlay.start())
                        button.setChecked(false);
                } else if (overlay.isRunning()) {
                    overlay.stop();
                }
            });

            conePane = new PaneBuilder(view)
                    .setMetaValue(Pane.RELATIVE_LOCATION, Pane.Location.Default)
                    .setMetaValue(Pane.PREFERRED_WIDTH_RATIO, 0.5D)
                    .setMetaValue(Pane.PREFERRED_HEIGHT_RATIO, 0.5D)
                    .build();
        }

        coneToggle.setChecked(overlay.isRunning());
        if (!uiService.isPaneVisible(conePane)) {
            uiService.showPane(conePane, null);
        }
    }

}
