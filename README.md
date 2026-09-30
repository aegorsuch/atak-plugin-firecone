# Firecone

Firecone is an ATAK 5.6.0 plugin that draws cones on friendly teammate markers from their normal ATAK position and course-over-ground reports. Teammates do not need the plugin. These cones indicate **direction of travel, not the direction their phones point**; normal CoT does not transmit device orientation. Moving cones match their teammate marker color; when teammates stop, the last observed travel heading stays grey until ATAK marks the contact stale. Teammates without an observed moving course do not get a cone.

Open the Firecone toolbar pane and switch **Teammate cones** on or off. Cones have a fixed 60-degree width and 500-meter range, and follow teammate position and course updates. They are removed when switched off or when the plugin stops. No additional CoT messages are sent.

The Android package and plugin extension use `com.atakmap.android.firecone.plugin`, independent of Houndmaster. Configure a local ATAK SDK in `local.properties` to build, for example with `.\gradlew.bat :app:assembleCivDebug`.

## Rights

Unlimited Rights granted to TAK Product Center.

## Point of Contact

Alex Gorsuch on chat.tak.gov or Signal.

## Repositories

The [TAK Forge repository](https://git.tak.gov/aegorsuch/atak-plugin-firecone#) is canonical. GitHub is a secondary repository.
