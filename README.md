# Firecone

Firecone is an ATAK 5.6.0 plugin that draws cones on friendly teammate markers from their normal ATAK position and course-over-ground reports. Teammates do not need the plugin. These cones indicate **direction of travel, not the direction their phones point**; normal CoT does not transmit device orientation. Moving cones match their teammate marker color; when teammates stop, the last observed travel heading stays grey until ATAK marks the contact stale. Teammates without an observed moving course do not get a cone.

Open the Firecone toolbar pane and switch **Teammate cones** on or off. Cones have a fixed 60-degree width and 500-meter range, and follow teammate position and course updates. They are removed when switched off or when the plugin stops. No additional CoT messages are sent.

The Android package and plugin extension use `com.atakmap.android.firecone.plugin`. Configure a local ATAK SDK in `local.properties` to build, for example with `.\gradlew.bat :app:assembleCivDebug`.

## Rights

Unlimited Rights granted to TAK Product Center.

## Point of Contact

Alex Gorsuch on chat.tak.gov or Signal.

## Repositories

The [TAK Forge repository](https://git.tak.gov/aegorsuch/atak-plugin-firecone#) is canonical. GitHub is a secondary repository.

## TAK Forge CI/CD

`.gitlab-ci.yml` uses the shared `devsecops/gitlab-ci-common` build-and-sign
template, matching Houndmaster. Pushes to `develop` run `release_build_and_sign`
with JDK 17 for the `civ` variant. Other branches do not run this build job.
Firecone continues to target ATAK 5.6.0.

The shared launcher handles authenticated TAK dependency access, building,
signing, and build/report artifacts. It requires access to the shared template,
TAK runners, artifact repositories, and signing service. Keep credentials and
signing keys in Forge CI services/configuration, not in Git.

The build supports `takrepo.url`, `takrepo.user`, and `takrepo.password` Gradle/local
properties and the launcher's underscore-form `takrepo_url`, `takrepo_user`, and
`takrepo_password` properties. Dotted properties take precedence. The launcher
can provide a root-level, untracked `signing.properties` with `storeFile`,
`storePassword`, `keyAlias`, and `keyPassword`; a relative `storeFile` is resolved
from `app`. Without that file, the existing local signing defaults are preserved.

The shared template controls publication and distribution separately from the
build; a successful develop build is not production approval. This pipeline
runs on canonical TAK Forge only and does not update the GitHub backup.
