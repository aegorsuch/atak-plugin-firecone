# Firecone

Firecone is an ATAK 5.6.0 plugin that draws cones on friendly teammate markers from their normal ATAK position and course-over-ground reports. Teammates do not need the plugin. These cones indicate **direction of travel, not the direction their phones point**; normal CoT does not transmit device orientation. Moving cones match their teammate marker color; when teammates stop, the last observed travel heading stays grey until 30 seconds after the last moving report. Cones disappear after that timeout without a new moving report, or when ATAK marks the contact stale. Teammates without an observed moving course do not get a cone.

Open the Firecone toolbar pane and switch **Teammate cones** on or off. Cones have a fixed 60-degree width, 50-meter range, and 30-second heading timeout. Cones follow teammate position and course updates and are removed when switched off or when the plugin stops. No additional CoT messages are sent.

The Android package and plugin extension use `com.atakmap.android.firecone.plugin`. Configure a local ATAK SDK in `local.properties` to build, for example with `.\gradlew.bat :app:assembleCivDebug`. The CIV APK is named `ATAK-Plugin-Firecone-<ATAK-version>-<revision>.apk` (for example, `ATAK-Plugin-Firecone-5.6.0-490c86a.apk`).

## Rights

Unlimited Rights granted to TAK Product Center.

## Point of Contact

Alex Gorsuch on chat.tak.gov or Signal.

## Repositories

The [TAK Forge repository](https://git.tak.gov/aegorsuch/atak-plugin-firecone#) is canonical. GitHub is a secondary repository.

## TAK Forge CI/CD

`.gitlab-ci.yml` uses the shared `devsecops/gitlab-ci-common` build-and-sign
template, matching Houndmaster. Pushes to `main` run `release_build_and_sign`
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
build; a successful main build is not production approval. This pipeline
runs on canonical TAK Forge only. The separate publisher below updates the
GitHub backup after a successful protected `main` build.

## Rolling GitHub release

The protected `main` pipeline publishes only its signed CIV APK to the
public GitHub backup as the stable release **TAK.gov Forge CI/CD Pipeline Release
(<plugin-version>-p<project-pipeline-IID>)**
(`pipeline-latest`) with the asset `Firecone-<plugin-version>-p<IID>.apk`. The
publisher verifies the APK signature and the uploaded asset digest, serializes
updates, and skips an outdated pipeline. It does not change numbered releases
or unrelated release assets. Version and code come from the signed APK using
`aapt dump badging`, not from the filename or current checkout. Notes include
the full embedded version, channel, global pipeline ID and project IID (when
available), canonical pipeline URL, exact source SHA, separate SHA256, and a
readable download link and native asset label matching the APK filename without
hashes. If no project IID is available, `-code<versionCode>` replaces `-p<IID>`;
an already matching pipeline suffix is not duplicated. Hidden managed boundaries
and pipeline metadata allow repeat updates while preserving manual notes.
Only recognized legacy publisher notes are migrated; unknown text is retained.
Pipelines older than either the canonical head or published pipeline are skipped.
Previously published downloads, including `ATAK-Plugin-Firecone-latest.apk`,
are retained without renaming, replacement or cosmetic deletion. Versioned
download URLs are immutable: retries reuse identical verified bytes and fail
on a conflicting digest. The managed marker records the current asset ID/name;
manual/unowned assets are never cleaned up based on filename patterns.

Before enabling this publisher, configure a `GITHUB_RELEASE_TOKEN` CI/CD
variable in the canonical TAK Forge project. Use a fine-grained token limited
to this GitHub repository with **Contents: read and write** permission; mark
the variable **protected** and **masked**, with environment scope `*`, and
ensure `main` is protected. The token is read only from this CI variable;
the job fails clearly if it is missing. Do not use a personal/local `gh` or
`glab` token, and do not put credentials in the repository. The publisher also
checks the canonical `main` branch head through the pipeline checkout and
skips outdated commits without requiring another CI credential. The
`publish_github_pipeline_release` job runs only on the canonical Forge host and
project, after both the signed build and the offline publisher tests succeed.
It downloads the signed build's artifacts without rebuilding or resigning
them. Its existing launcher image must provide Python 3.10+, Git, and Android
`apksigner` and `aapt`. Tools are resolved from `PATH`, then installed stable
build-tools under `ANDROID_SDK_ROOT` or `ANDROID_HOME` (highest version first);
missing tools fail explicitly, without downloading or installing anything.
The publisher script's mocked tests can be run offline with
`python -m unittest discover -s scripts -p "test_*.py"`.
