import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from publish_github_release import (
    PublishError,
    release_metadata,
    STABLE_ASSET_NAME,
    publish,
    _asset,
    _android_tool,
)


APK_BYTES = b"verified CIV APK bytes"
APK_DIGEST = hashlib.sha256(APK_BYTES).hexdigest()


class Response:
    def __init__(self, body: object, status: int = 200):
        self.status = status
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class FakeGitHub:
    def __init__(
        self,
        *,
        stable_asset: bool = True,
        bad_digest: bool = False,
        omit_digest: bool = False,
        missing_release: bool = False,
        fail_promotion: bool = False,
        previous_body: str = "",
        versioned_asset: bool = False,
        versioned_digest: str = APK_DIGEST,
        owned_asset: bool = False,
        old_identity: int = 11,
        corrupt_backup: bool = False,
        fail_cleanup: bool = False,
    ):
        self.calls = []
        self.stable_asset = stable_asset
        self.bad_digest = bad_digest
        self.omit_digest = omit_digest
        self.missing_release = missing_release
        self.fail_promotion = fail_promotion
        self.previous_body = previous_body
        self.versioned_asset = versioned_asset
        self.versioned_digest = versioned_digest
        self.owned_asset = owned_asset
        self.old_identity = old_identity
        self.corrupt_backup = corrupt_backup
        self.fail_cleanup = fail_cleanup

    def __call__(self, request, timeout=60):
        url = urlsplit(request.full_url)
        if (
            url.scheme != "https"
            or url.netloc not in {"api.github.com", "uploads.github.com"}
            or not url.path.startswith("/repos/aegorsuch/atak-plugin-firecone/")
        ):
            raise AssertionError("Requests must target the Firecone GitHub mirror.")
        if request.get_header("Authorization") != "Bearer masked-github-token":
            raise AssertionError("Requests must use the CI token.")
        path = url.path
        method = request.method
        body = (
            json.loads(request.data)
            if request.data and "uploads.github.com" not in request.full_url
            else None
        )
        self.calls.append((method, path, body))

        if path.endswith("/releases/tags/pipeline-latest"):
            if self.missing_release:
                from urllib.error import HTTPError

                raise HTTPError(request.full_url, 404, "not found", {}, None)
            return Response(
                {
                    "id": 7,
                    "body": self.previous_body,
                    "upload_url": "https://uploads.github.com/repos/aegorsuch/"
                    "atak-plugin-firecone/releases/7/assets{?name,label}",
                }
            )
        if path.endswith("/releases") and method == "POST":
            return Response(
                {
                    "id": 7,
                    "upload_url": "https://uploads.github.com/repos/aegorsuch/"
                    "atak-plugin-firecone/releases/7/assets{?name,label}",
                }
            )
        if path.endswith("/releases/7/assets") and method == "GET":
            assets = []
            if self.owned_asset:
                assets.append({
                    "id": self.old_identity, "name": "Firecone-0.1-p6.apk",
                    "size": len(APK_BYTES), "state": "uploaded",
                    "digest": f"sha256:{APK_DIGEST}",
                })
            if self.versioned_asset:
                assets.append({
                    "id": 12, "name": "Firecone-0.1-p7.apk",
                    "label": "Firecone-0.1-p7.apk", "state": "uploaded",
                    "size": len(APK_BYTES), "digest": f"sha256:{self.versioned_digest}",
                })
            if self.stable_asset:
                assets.append(
                    {
                            "id": 11,
                            "name": STABLE_ASSET_NAME,
                        "state": "uploaded",
                        "size": 3,
                        "digest": "sha256:old",
                    }
                )
            assets.append(
                {
                    "id": 13,
                    "name": "unrelated-document.pdf",
                    "state": "uploaded",
                    "size": 200,
                }
            )
            return Response(assets)
        if path.endswith("/assets/12") and method == "GET":
            if request.get_header("Accept") != "application/octet-stream":
                raise AssertionError("APK content must be requested for digest fallback.")
            return Response(APK_BYTES)
        if path.endswith("/assets/11") and method == "GET":
            return Response(b"corrupt" if self.corrupt_backup else APK_BYTES)
        if "uploads.github.com" in request.full_url and method == "POST":
            if request.data != APK_BYTES:
                raise AssertionError("The signed APK bytes must be preserved.")
            if parse_qs(url.query) != {"name": ["firecone-candidate-99-aaaaaaa.apk"]}:
                raise AssertionError("The upload must use a pipeline-specific candidate.")
            return Response(
                {
                    "id": 12,
                    "name": "firecone-candidate-99-aaaaaaa.apk",
                    "state": "uploaded",
                    "size": len(APK_BYTES),
                    "digest": (
                        None
                        if self.omit_digest
                        else f"sha256:{'0' * 64 if self.bad_digest else APK_DIGEST}"
                    ),
                }
            )
        if method == "PATCH" and path.endswith("/assets/11"):
            return Response({"id": 11})
        if method == "PATCH" and path.endswith("/assets/12"):
            if self.fail_promotion:
                return Response({"message": "promotion failed"}, 500)
            return Response(
                {
                    "id": 12,
                    "name": "Firecone-0.1-p7.apk",
                    "label": "Firecone-0.1-p7.apk",
                    "state": "uploaded",
                    "size": len(APK_BYTES),
                    "digest": None if self.omit_digest else f"sha256:{APK_DIGEST}",
                }
            )
        if method == "PATCH" and path.endswith("/releases/7"):
            if "name" not in body:
                return Response({"id": 7, "body": body["body"]})
            return Response(
                {"id": 7, "name": body["name"], "draft": False, "prerelease": False}
            )
        if method == "PATCH" and path.endswith("/git/refs/tags/pipeline-latest"):
            return Response({"ref": "refs/tags/pipeline-latest"})
        if method == "DELETE":
            if self.fail_cleanup:
                return Response({"message": "delete failed"}, 500)
            return Response(b"", 204)
        raise AssertionError(f"Unexpected request: {method} {request.full_url} {body}")


def environment(**updates):
    env = {
        "CI_SERVER_HOST": "git.tak.gov",
        "CI_PROJECT_PATH": "aegorsuch/atak-plugin-firecone",
        "CI_COMMIT_BRANCH": "main",
        "CI_COMMIT_REF_PROTECTED": "true",
        "CI_COMMIT_SHA": "a" * 40,
        "CI_COMMIT_SHORT_SHA": "aaaaaaa",
        "CI_PIPELINE_ID": "42",
        "CI_PIPELINE_IID": "7",
        "CI_PIPELINE_URL": "https://git.tak.gov/aegorsuch/atak-plugin-firecone/-/pipelines/42",
        "CI_JOB_ID": "99",
        "CI_JOB_URL": "https://git.tak.gov/jobs/99",
        "GITHUB_RELEASE_TOKEN": "masked-github-token",
    }
    env.update(updates)
    return env


class PublishReleaseTests(unittest.TestCase):
    def setUp(self):
        network = patch(
            "urllib.request.OpenerDirector.open",
            side_effect=AssertionError("Publisher tests must not access the network."),
        )
        network.start()
        self.addCleanup(network.stop)
        tool = patch("publish_github_release._android_tool", side_effect=lambda name: name)
        tool.start()
        self.addCleanup(tool.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        Path(self.temp_dir.name, "ATAK-Plugin-Firecone-5.6.0-aaaaaaa.apk").write_bytes(
            APK_BYTES
        )
        self.signer = patch("publish_github_release.subprocess.run")
        self.mock_signer = self.signer.start()
        self.mock_signer.side_effect = self.fake_commands
        self.addCleanup(self.signer.stop)
        self.addCleanup(self.temp_dir.cleanup)

    @staticmethod
    def fake_commands(args, **_):
        if args[0] == "git":
            return SimpleNamespace(
                returncode=0, stdout=f"{'a' * 40}\trefs/heads/main\n"
            )
        if args[:3] == ["apksigner", "verify", "--verbose"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:3] == ["aapt", "dump", "badging"]:
            return SimpleNamespace(
                returncode=0,
                stdout="package: name='com.atakmap.android.firecone.plugin' "
                "versionCode='123' versionName='0.1 (aaaaaaa) - [5.6.0]'",
            )
        raise AssertionError(f"Unexpected subprocess: {args}")

    def test_publishes_versioned_asset_and_preserves_legacy_download(self):
        github = FakeGitHub()

        self.assertTrue(publish(environment(), github, Path(self.temp_dir.name)))

        promoted = [
            call
            for call in github.calls
            if call[0] == "PATCH" and call[1].endswith("/assets/12")
        ]
        removed = [call for call in github.calls if call[0] == "DELETE"]
        self.assertEqual(len(promoted), 1)
        self.assertEqual(removed, [])
        self.assertFalse(any(call[1].endswith("/assets/11") for call in github.calls))
        upload_index = next(
            i for i, call in enumerate(github.calls) if call[0] == "POST"
        )
        promotion_index = next(
            i
            for i, call in enumerate(github.calls)
            if call[0] == "PATCH" and call[1].endswith("/assets/12")
        )
        self.assertLess(
            upload_index,
            promotion_index,
        )
        self.assertEqual(
            [
                call
                for call in github.calls
                if call[0] == "PATCH" and "/assets/" in call[1]
            ][0][2],
            {"name": "Firecone-0.1-p7.apk", "label": "Firecone-0.1-p7.apk"},
        )
        self.assertFalse(any(call[1].endswith("/assets/13") for call in github.calls))
        update = next(
            call for call in github.calls
            if call[0] == "PATCH" and call[1].endswith("/releases/7")
        )
        self.assertEqual(
            update[2]["name"], "TAK.gov Forge CI/CD Pipeline Release (0.1-p7)"
        )
        self.assertIn("project pipeline **7**", update[2]["body"])
        self.assertIn("Source commit: `" + "a" * 40 + "`", update[2]["body"])
        self.assertEqual(
            promoted[0][2]["label"], "Firecone-0.1-p7.apk"
        )
        self.assertFalse(update[2]["draft"])
        self.assertFalse(update[2]["prerelease"])
        self.assertIn(APK_DIGEST, update[2]["body"])
        self.assertIn(environment()["CI_PIPELINE_URL"], update[2]["body"])
        self.assertIn('"asset_id": 12', update[2]["body"])
        self.assertIn('"asset_name": "Firecone-0.1-p7.apk"', update[2]["body"])

    def test_missing_token_fails_before_subprocess_or_github_access(self):
        github = FakeGitHub()

        with self.assertRaisesRegex(PublishError, "GITHUB_RELEASE_TOKEN is missing"):
            publish(environment(GITHUB_RELEASE_TOKEN=""), github, Path(self.temp_dir.name))

        self.mock_signer.assert_not_called()
        self.assertEqual(github.calls, [])

    def test_rejects_noncanonical_or_unprotected_pipelines_before_access(self):
        for key, value in (
            ("CI_SERVER_HOST", "github.com"),
            ("CI_PROJECT_PATH", "someone/atak-plugin-firecone"),
            ("CI_COMMIT_BRANCH", "feature"),
            ("CI_COMMIT_REF_PROTECTED", "false"),
        ):
            with self.subTest(setting=key):
                github = FakeGitHub()
                with self.assertRaises(PublishError):
                    publish(environment(**{key: value}), github, Path(self.temp_dir.name))
                self.assertEqual(github.calls, [])
        self.mock_signer.assert_not_called()

    def test_missing_or_ambiguous_apks_are_not_uploaded(self):
        apk = next(Path(self.temp_dir.name).glob("*.apk"))
        apk.unlink()
        for count in (0, 2):
            with self.subTest(count=count):
                if count:
                    for name in ("ATAK-Plugin-Firecone-one.apk", "ATAK-Plugin-Firecone-two.apk"):
                        Path(self.temp_dir.name, name).write_bytes(APK_BYTES)
                github = FakeGitHub()
                with self.assertRaisesRegex(PublishError, "Expected exactly one CIV APK"):
                    publish(environment(), github, Path(self.temp_dir.name))
                self.assertEqual(github.calls, [])

    def test_canonical_head_failure_prevents_github_access(self):
        self.mock_signer.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
        self.mock_signer.side_effect = None
        github = FakeGitHub()

        with self.assertRaisesRegex(PublishError, "canonical main branch head"):
            publish(environment(), github, Path(self.temp_dir.name))

        self.assertEqual(github.calls, [])

    def test_github_error_is_reported_without_response_body_or_token(self):
        def unauthorized(*_, **__):
            return Response({"message": "sensitive API response"}, 401)

        with self.assertRaises(PublishError) as error:
            publish(environment(), unauthorized, Path(self.temp_dir.name))

        self.assertIn("HTTP 401", str(error.exception))
        self.assertNotIn(environment()["GITHUB_RELEASE_TOKEN"], str(error.exception))
        self.assertNotIn("sensitive API response", str(error.exception))

    def test_bad_upload_digest_does_not_change_existing_release_asset(self):
        github = FakeGitHub(bad_digest=True)

        with self.assertRaisesRegex(RuntimeError, "SHA-256 digest"):
            publish(environment(), github, Path(self.temp_dir.name))

        self.assertFalse(
            any(call[0] in {"PATCH", "DELETE"} for call in github.calls)
        )

    def test_missing_server_digest_is_verified_from_uploaded_bytes(self):
        github = FakeGitHub(omit_digest=True)

        self.assertTrue(publish(environment(), github, Path(self.temp_dir.name)))

        downloads = [
            call
            for call in github.calls
            if call[0] == "GET" and call[1].endswith("/assets/12")
        ]
        self.assertEqual(len(downloads), 2)

    def test_failed_promotion_does_not_touch_previous_downloads(self):
        github = FakeGitHub(fail_promotion=True)

        with self.assertRaisesRegex(RuntimeError, "GitHub PATCH.*HTTP 500"):
            publish(environment(), github, Path(self.temp_dir.name))

        renames = [
            call
            for call in github.calls
            if call[0] == "PATCH" and call[1].endswith("/assets/11")
        ]
        self.assertEqual(renames, [])
        self.assertFalse(any(call[0] == "DELETE" for call in github.calls))

    def test_unsigned_apk_is_not_uploaded(self):
        def unsigned_command(args, **_):
            if args[0] == "git":
                return SimpleNamespace(
                    returncode=0, stdout=f"{'a' * 40}\trefs/heads/main\n"
                )
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        self.mock_signer.side_effect = unsigned_command
        github = FakeGitHub()

        with self.assertRaisesRegex(RuntimeError, "signature verification"):
            publish(environment(), github, Path(self.temp_dir.name))

        self.assertEqual(len(github.calls), 0)

    def test_stale_pipeline_does_not_contact_github(self):
        def stale_commands(args, **_):
            if args[0] == "git":
                return SimpleNamespace(
                    returncode=0, stdout=f"{'b' * 40}\trefs/heads/main\n"
                )
            self.fail("The APK signer must not run for a stale pipeline.")

        self.mock_signer.side_effect = stale_commands
        github = FakeGitHub()
        self.assertFalse(publish(environment(), github, Path(self.temp_dir.name)))
        self.assertEqual(github.calls, [])
        self.assertEqual(self.mock_signer.call_count, 1)

    def test_first_release_has_required_title_and_is_published_stable(self):
        github = FakeGitHub(stable_asset=False, missing_release=True)

        self.assertTrue(publish(environment(), github, Path(self.temp_dir.name)))

        create = next(
            call
            for call in github.calls
            if call[0] == "POST" and call[1].endswith("/releases")
        )
        self.assertEqual(
            create[2]["name"], "TAK.gov Forge CI/CD Pipeline Release (0.1-p7)"
        )
        self.assertEqual(create[2]["tag_name"], "pipeline-latest")
        self.assertTrue(create[2]["draft"])
        self.assertFalse(create[2]["prerelease"])
        self.assertTrue(
            any(
                call[0] == "PATCH"
                and call[1].endswith("/git/refs/tags/pipeline-latest")
                and call[2] == {"sha": "a" * 40, "force": True}
                for call in github.calls
            )
        )

    def test_manual_notes_survive_repeated_managed_updates(self):
        manual = "Operator notes: keep this exactly.\n\n"
        _, notes, label = release_metadata(
            environment(), "0.1 (aaaaaaa) - [5.6.0]", "123", APK_DIGEST, manual
        )
        _, updated, _ = release_metadata(
            environment(), "0.2 (bbbbbbb) - [5.6.0]", "124", APK_DIGEST, notes
        )
        self.assertTrue(updated.startswith(manual))
        self.assertNotIn("0.1 (aaaaaaa)", updated)
        self.assertEqual(updated.count("<!-- firecone-pipeline-release:start -->"), 1)
        self.assertNotIn(APK_DIGEST, label)

    def test_known_legacy_notes_are_migrated_without_duplicate_checksum(self):
        legacy = (
            f"Signed CIV APK from TAK.gov pipeline [41](https://git.tak.gov/p/41) "
            f"at `{'a' * 40}`.\n\nBuild job [99](https://git.tak.gov/j/99); "
            f"artifact `old.apk`; SHA-256 `{APK_DIGEST}`.\n\nManual tail."
        )
        _, notes, _ = release_metadata(
            environment(), "0.1", "123", APK_DIGEST, legacy
        )
        self.assertIn("Manual tail.", notes)
        self.assertNotIn("old.apk", notes)
        self.assertEqual(notes.count("- SHA256:"), 1)

    def test_plain_legacy_live_notes_are_migrated(self):
        legacy = (
            "Signed CIV APK from TAK.gov pipeline 41 "
            f"(https://git.tak.gov/p/41) at commit {'a' * 40}.\n\n"
            "Build job 99 (https://git.tak.gov/j/99). Artifact old.apk. "
            f"SHA-256: {APK_DIGEST.upper()}."
        )
        _, notes, _ = release_metadata(environment(), "0.1", "123", APK_DIGEST, legacy)
        self.assertNotIn("old.apk", notes)
        self.assertEqual(notes.count("- SHA256:"), 1)

    def test_newer_published_pipeline_prevents_mutation(self):
        _, previous, _ = release_metadata(
            environment(
                CI_PIPELINE_ID="43",
                CI_PIPELINE_URL="https://git.tak.gov/aegorsuch/atak-plugin-firecone/-/pipelines/43",
            ), "0.1", "123", APK_DIGEST
        )
        github = FakeGitHub(previous_body=previous)
        self.assertFalse(publish(environment(), github, Path(self.temp_dir.name)))
        self.assertEqual([call[0] for call in github.calls], ["GET"])

    def test_version_inspection_failure_prevents_github_access(self):
        def commands(args, **kwargs):
            if args[0] == "aapt":
                return SimpleNamespace(returncode=1, stdout="")
            return self.fake_commands(args, **kwargs)
        self.mock_signer.side_effect = commands
        github = FakeGitHub()
        with self.assertRaisesRegex(PublishError, "versionCode"):
            publish(environment(), github, Path(self.temp_dir.name))
        self.assertEqual(github.calls, [])

    def test_metadata_without_project_iid_does_not_invent_one(self):
        title, notes, label = release_metadata(
            environment(CI_PIPELINE_IID=""), "0.1", "123", APK_DIGEST
        )
        self.assertNotIn("project pipeline **", notes)
        self.assertEqual(label, "Firecone-0.1-code123.apk")
        self.assertEqual(title, "TAK.gov Forge CI/CD Pipeline Release (0.1-code123)")

    def test_existing_pipeline_suffix_is_not_duplicated(self):
        title, _, label = release_metadata(
            environment(), "0.1-p7", "123", APK_DIGEST
        )
        self.assertEqual(label, "Firecone-0.1-p7.apk")
        self.assertEqual(title, "TAK.gov Forge CI/CD Pipeline Release (0.1-p7)")
        with self.assertRaisesRegex(PublishError, "conflicts"):
            release_metadata(environment(), "0.1-p8", "123", APK_DIGEST)

    def test_invalid_filename_version_is_rejected(self):
        for version in ("../bad", "0.1+hash", "", "0.1\nunexpected"):
            with self.subTest(version=version), self.assertRaises(PublishError):
                release_metadata(environment(), version, "123", APK_DIGEST)

    def test_asset_lookup_paginates_retained_downloads(self):
        calls = []
        def pages(request, **_):
            calls.append(request.full_url)
            if parse_qs(urlsplit(request.full_url).query)["page"] == ["1"]:
                return Response([{"name": f"manual-{i}"} for i in range(100)])
            return Response([{"id": 12, "name": "Firecone-0.1-p7.apk"}])
        self.assertEqual(
            _asset(pages, 7, "Firecone-0.1-p7.apk", "mock")["id"], 12
        )
        self.assertEqual(len(calls), 2)
        self.assertIn("page=2", calls[1])

    @staticmethod
    def owned_previous_body():
        return release_metadata(
            environment(
                CI_PIPELINE_ID="41", CI_PIPELINE_IID="6",
                CI_PIPELINE_URL="https://git.tak.gov/aegorsuch/atak-plugin-firecone/-/pipelines/41",
            ), "0.1", "122", APK_DIGEST, asset_id=11,
        )[1]

    def test_owned_previous_apk_is_backed_up_then_deleted_after_verified_publish(self):
        github = FakeGitHub(owned_asset=True, previous_body=self.owned_previous_body())
        self.assertTrue(publish(environment(), github, Path(self.temp_dir.name)))
        deletes = [call for call in github.calls if call[0] == "DELETE"]
        self.assertEqual([call[1] for call in deletes], [
            "/repos/aegorsuch/atak-plugin-firecone/releases/assets/11"
        ])
        deleted_at = github.calls.index(deletes[0])
        self.assertTrue(any(
            call[0] == "PATCH" and "/git/refs/tags/" in call[1]
            for call in github.calls[:deleted_at]
        ))
        backup = Path(self.temp_dir.name, ".github-release-backup")
        self.assertEqual((backup / "11.apk").read_bytes(), APK_BYTES)
        self.assertEqual(json.loads((backup / "11.json").read_text())["asset"]["id"], 11)
        self.assertFalse(any(call[1].endswith("/assets/13") for call in github.calls))
        updates = [c for c in github.calls if c[0] == "PATCH" and c[1].endswith("/releases/7")]
        self.assertIn('"previous_assets"', updates[0][2]["body"])
        self.assertNotIn('"previous_assets"', updates[-1][2]["body"])

    def test_owned_asset_identity_mismatch_is_never_deleted(self):
        github = FakeGitHub(
            owned_asset=True, previous_body=self.owned_previous_body(), old_identity=99
        )
        with self.assertRaisesRegex(PublishError, "live identity"):
            publish(environment(), github, Path(self.temp_dir.name))
        self.assertFalse(any(call[0] == "DELETE" for call in github.calls))

    def test_backup_checksum_failure_prevents_deletion(self):
        github = FakeGitHub(
            owned_asset=True, previous_body=self.owned_previous_body(), corrupt_backup=True
        )
        with self.assertRaisesRegex(PublishError, "back up and verify"):
            publish(environment(), github, Path(self.temp_dir.name))
        self.assertFalse(any(call[0] == "DELETE" for call in github.calls))

    def test_cleanup_failure_keeps_claim_for_same_pipeline_retry(self):
        github = FakeGitHub(
            owned_asset=True, previous_body=self.owned_previous_body(), fail_cleanup=True
        )
        with self.assertRaisesRegex(PublishError, "cleanup failed"):
            publish(environment(), github, Path(self.temp_dir.name))
        pending = next(
            c[2]["body"] for c in github.calls
            if c[0] == "PATCH" and c[1].endswith("/releases/7")
        )
        retry = FakeGitHub(
            owned_asset=True, versioned_asset=True, previous_body=pending
        )
        self.assertTrue(publish(environment(), retry, Path(self.temp_dir.name)))
        self.assertTrue(any(c[0] == "DELETE" and c[1].endswith("/assets/11") for c in retry.calls))
        self.assertFalse(any(c[0] == "POST" for c in retry.calls))

    def test_matching_versioned_asset_is_reused_without_upload_or_rename(self):
        github = FakeGitHub(versioned_asset=True)
        self.assertTrue(publish(environment(), github, Path(self.temp_dir.name)))
        self.assertFalse(any(call[0] in {"POST", "DELETE"} for call in github.calls))
        self.assertFalse(any("/assets/" in call[1] for call in github.calls))

    def test_different_bytes_at_versioned_url_are_never_replaced(self):
        github = FakeGitHub(versioned_asset=True, versioned_digest="0" * 64)
        with self.assertRaisesRegex(PublishError, "SHA-256 digest"):
            publish(environment(), github, Path(self.temp_dir.name))
        self.assertTrue(all(call[0] == "GET" for call in github.calls))

    def test_historical_channel_is_not_relabelled_as_main(self):
        _, notes, _ = release_metadata(
            environment(CI_COMMIT_BRANCH="develop"), "0.1", "123", APK_DIGEST
        )
        self.assertIn("stable Firecone CIV develop-channel build.", notes)
        self.assertIn("on TAK.gov `develop`", notes)

    def test_visible_notes_match_reference_layout_exactly(self):
        import re
        _, notes, _ = release_metadata(
            environment(), "0.1 (aaaaaaa) - [5.6.0]", "123", APK_DIGEST
        )
        visible = re.sub(r"<!--.*?-->", "", notes, flags=re.DOTALL).strip()
        self.assertEqual(visible, (
            "Automatically published stable Firecone CIV main-channel build.\n\n"
            "- APK version: **0.1 (aaaaaaa) - [5.6.0]** (versionCode **123**)\n"
            "- Build: GitLab pipeline **42** (project pipeline **7**)\n"
            "- Pipeline: https://git.tak.gov/aegorsuch/atak-plugin-firecone/-/pipelines/42\n"
            f"- Source commit: `{'a' * 40}` on TAK.gov `main`\n"
            f"- SHA256: `{APK_DIGEST}`\n\n"
            "Install the APK above. GitHub's \"Source code\" archives come from the "
            "fixed release anchor tag, not from this build; the source commit above "
            "is authoritative and may not yet be mirrored to GitHub."
        ))

    def test_noncanonical_pipeline_link_is_rejected(self):
        with self.assertRaisesRegex(PublishError, "canonical pipeline"):
            release_metadata(
                environment(CI_PIPELINE_URL="https://example.com/42"),
                "0.1", "123", APK_DIGEST,
            )

    def test_ambiguous_markers_and_incomplete_source_are_rejected(self):
        for previous in (
            "<!-- firecone-pipeline-release:start -->",
            "<!-- firecone-pipeline-release:end --><!-- firecone-pipeline-release:start -->",
        ):
            with self.subTest(previous=previous), self.assertRaises(PublishError):
                release_metadata(environment(), "0.1", "123", APK_DIGEST, previous)
        with self.assertRaises(PublishError):
            release_metadata(environment(CI_COMMIT_SHA="aaaaaaa"), "0.1", "123", APK_DIGEST)


class AndroidToolTests(unittest.TestCase):
    def test_path_tools_take_precedence(self):
        with patch("publish_github_release.shutil.which", return_value="sdk-tool"):
            self.assertEqual(_android_tool("aapt"), "sdk-tool")

    def test_sdk_environment_resolves_highest_stable_build_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            for version in ("9.0.0", "35.0.0", "36.0.0-rc1"):
                directory = Path(folder, "build-tools", version)
                directory.mkdir(parents=True)
                (directory / ("aapt.exe" if os.name == "nt" else "aapt")).write_bytes(b"tool")
                if os.name != "nt":
                    (directory / "aapt").chmod(0o755)
            for key in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
                with self.subTest(key=key), patch.dict(
                    os.environ, {key: folder}, clear=True
                ), patch("publish_github_release.shutil.which", return_value=None):
                    self.assertIn("35.0.0", _android_tool("aapt"))

    def test_missing_tool_fails_without_install_or_download(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "publish_github_release.shutil.which", return_value=None
        ):
            with self.assertRaisesRegex(PublishError, "ANDROID_SDK_ROOT/ANDROID_HOME"):
                _android_tool("apksigner")


if __name__ == "__main__":
    unittest.main()
