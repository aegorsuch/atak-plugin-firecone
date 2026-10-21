import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from publish_github_release import (
    RELEASE_TITLE,
    STABLE_ASSET_NAME,
    publish,
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
    ):
        self.calls = []
        self.stable_asset = stable_asset
        self.bad_digest = bad_digest
        self.omit_digest = omit_digest
        self.missing_release = missing_release
        self.fail_promotion = fail_promotion

    def __call__(self, request, timeout=60):
        path = urlsplit(request.full_url).path
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
        if "uploads.github.com" in request.full_url and method == "POST":
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
                    "name": STABLE_ASSET_NAME,
                    "state": "uploaded",
                    "size": len(APK_BYTES),
                    "digest": None if self.omit_digest else f"sha256:{APK_DIGEST}",
                }
            )
        if method == "PATCH" and path.endswith("/releases/7"):
            return Response(
                {"id": 7, "name": RELEASE_TITLE, "draft": False, "prerelease": False}
            )
        if method == "PATCH" and path.endswith("/git/refs/tags/pipeline-latest"):
            return Response({"ref": "refs/tags/pipeline-latest"})
        if method == "DELETE":
            return Response(b"", 204)
        raise AssertionError(f"Unexpected request: {method} {request.full_url} {body}")


def environment(**updates):
    env = {
        "CI_PROJECT_PATH": "aegorsuch/atak-plugin-firecone",
        "CI_COMMIT_BRANCH": "main",
        "CI_COMMIT_SHA": "a" * 40,
        "CI_COMMIT_SHORT_SHA": "aaaaaaa",
        "CI_PIPELINE_ID": "42",
        "CI_PIPELINE_URL": "https://git.tak.gov/pipelines/42",
        "CI_JOB_ID": "99",
        "CI_JOB_URL": "https://git.tak.gov/jobs/99",
        "GITHUB_RELEASE_TOKEN": "masked-github-token",
    }
    env.update(updates)
    return env


class PublishReleaseTests(unittest.TestCase):
    def setUp(self):
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
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_replaces_only_rolling_asset_after_verified_upload(self):
        github = FakeGitHub()

        self.assertTrue(publish(environment(), github, Path(self.temp_dir.name)))

        promoted = [
            call
            for call in github.calls
            if call[0] == "PATCH" and call[1].endswith("/assets/12")
        ]
        removed = [call for call in github.calls if call[0] == "DELETE"]
        self.assertEqual(len(promoted), 1)
        self.assertEqual(len(removed), 1)
        self.assertTrue(removed[0][1].endswith("/assets/11"))
        upload_index = next(
            i for i, call in enumerate(github.calls) if call[0] == "POST"
        )
        backup_index = next(
            i
            for i, call in enumerate(github.calls)
            if call[0] == "PATCH" and call[1].endswith("/assets/11")
        )
        self.assertLess(
            upload_index,
            backup_index,
        )
        self.assertEqual(
            [
                call
                for call in github.calls
                if call[0] == "PATCH" and "/assets/" in call[1]
            ][0][2],
            {"name": "firecone-previous-99-aaaaaaa.apk"},
        )
        self.assertFalse(any(call[1].endswith("/assets/13") for call in github.calls))

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

    def test_failed_promotion_restores_previous_rolling_asset(self):
        github = FakeGitHub(fail_promotion=True)

        with self.assertRaisesRegex(RuntimeError, "GitHub PATCH.*HTTP 500"):
            publish(environment(), github, Path(self.temp_dir.name))

        renames = [
            call
            for call in github.calls
            if call[0] == "PATCH" and call[1].endswith("/assets/11")
        ]
        self.assertEqual(
            [call[2]["name"] for call in renames],
            ["firecone-previous-99-aaaaaaa.apk", STABLE_ASSET_NAME],
        )
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
        self.assertEqual(create[2]["name"], "TAK.gov CI/CD Pipeline Release")
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


if __name__ == "__main__":
    unittest.main()
