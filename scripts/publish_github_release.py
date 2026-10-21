#!/usr/bin/env python3
"""Publish the signed CIV APK from the current protected main commit."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


REPOSITORY = "aegorsuch/atak-plugin-firecone"
RELEASE_TAG = "pipeline-latest"
RELEASE_TITLE = "TAK.gov CI/CD Pipeline Release"
STABLE_ASSET_NAME = "ATAK-Plugin-Firecone-latest.apk"
GITHUB_API = "https://api.github.com"

Opener = Callable[..., Any]


class PublishError(RuntimeError):
    pass


def _required(env: dict[str, str], key: str) -> str:
    value = env.get(key, "")
    if not value:
        raise PublishError(f"Required CI setting {key} is missing.")
    return value


def _http(
    opener: Opener,
    method: str,
    url: str,
    token: str,
    *,
    body: dict[str, Any] | None = None,
    binary: bytes | None = None,
    content_type: str | None = None,
    accept: str = "application/vnd.github+json",
) -> tuple[int, bytes]:
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = binary
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=data, headers=headers, method=method)
    if token:
        request.add_unredirected_header("Authorization", "Bearer " + token)
    try:
        with opener(request, timeout=60) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()
    except OSError as error:
        raise PublishError(f"{method} request failed for {urlsplit(url).path}.") from error


def _json_response(status: int, body: bytes, context: str) -> dict[str, Any]:
    if status < 200 or status >= 300:
        raise PublishError(f"{context} failed with HTTP {status}.")
    try:
        result = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublishError(f"{context} returned invalid JSON.") from error
    if not isinstance(result, dict):
        raise PublishError(f"{context} returned an unexpected response.")
    return result


def _github_json(
    opener: Opener,
    method: str,
    path: str,
    token: str,
    *,
    body: dict[str, Any] | None = None,
    binary: bytes | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    status, response = _http(
        opener,
        method,
        f"{GITHUB_API}{path}",
        token,
        body=body,
        binary=binary,
        content_type=content_type,
    )
    return _json_response(status, response, f"GitHub {method} {path}")


def _latest_develop_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", "refs/heads/main"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise PublishError("Unable to check the canonical main branch head.") from error
    if result.returncode != 0:
        raise PublishError("Unable to check the canonical main branch head.")
    refs = [
        line.split()[0]
        for line in result.stdout.splitlines()
        if len(line.split()) == 2 and line.split()[1] == "refs/heads/main"
    ]
    if len(refs) != 1:
        raise PublishError("Git did not return exactly one canonical main branch head.")
    return refs[0]


def _verify_apk(apk: Path) -> str:
    if not apk.is_file() or apk.stat().st_size == 0:
        raise PublishError("The build artifact is missing or empty.")
    try:
        result = subprocess.run(
            ["apksigner", "verify", "--verbose", str(apk)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise PublishError("Android apksigner is unavailable in the CI image.") from error
    if result.returncode != 0:
        raise PublishError("The CIV APK failed Android signature verification.")
    digest = hashlib.sha256()
    with apk.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _asset(
    opener: Opener, release_id: int, name: str, token: str
) -> dict[str, Any] | None:
    path = f"/repos/{REPOSITORY}/releases/{release_id}/assets?per_page=100"
    status, response = _http(opener, "GET", f"{GITHUB_API}{path}", token)
    if status < 200 or status >= 300:
        raise PublishError(f"Unable to list assets for rolling release (HTTP {status}).")
    try:
        assets = json.loads(response)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublishError("GitHub returned an invalid release-assets response.") from error
    if not isinstance(assets, list):
        raise PublishError("GitHub returned an unexpected release-assets response.")
    matches = [item for item in assets if isinstance(item, dict) and item.get("name") == name]
    if len(matches) > 1:
        raise PublishError(f"The rolling release has duplicate {name} assets.")
    return matches[0] if matches else None


def _validate_uploaded_asset(
    opener: Opener,
    asset: dict[str, Any],
    name: str,
    size: int,
    digest: str,
    token: str,
) -> None:
    if (
        asset.get("name") != name
        or asset.get("state") != "uploaded"
        or asset.get("size") != size
    ):
        raise PublishError("GitHub did not confirm the uploaded APK name and size.")
    uploaded_digest = asset.get("digest")
    if uploaded_digest is None:
        status, content = _http(
            opener,
            "GET",
            f"{GITHUB_API}/repos/{REPOSITORY}/releases/assets/{asset['id']}",
            token,
            accept="application/octet-stream",
        )
        if status < 200 or status >= 300:
            raise PublishError(
                f"Unable to verify the uploaded APK bytes (HTTP {status})."
            )
        uploaded_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if uploaded_digest != f"sha256:{digest}":
        raise PublishError("GitHub did not confirm the uploaded APK SHA-256 digest.")


def publish(
    env: dict[str, str], opener: Opener = urlopen, cwd: Path | None = None
) -> bool:
    if env.get("CI_PROJECT_PATH") != REPOSITORY:
        raise PublishError("This publisher only supports the canonical Firecone project.")
    if env.get("CI_COMMIT_BRANCH") != "main":
        raise PublishError("This publisher only supports the main branch.")
    for key in (
        "CI_COMMIT_SHA",
        "CI_COMMIT_SHORT_SHA",
        "CI_PIPELINE_ID",
        "CI_PIPELINE_URL",
        "CI_JOB_ID",
        "CI_JOB_URL",
    ):
        _required(env, key)

    token = _required(env, "GITHUB_RELEASE_TOKEN")
    if _latest_develop_commit() != env["CI_COMMIT_SHA"]:
        print(
            f"Skipping stale pipeline {env['CI_PIPELINE_ID']}; "
            "the main branch has advanced."
        )
        return False

    directory = cwd or Path.cwd()
    artifacts = sorted(directory.glob("ATAK-Plugin-Firecone-*.apk"))
    if len(artifacts) != 1:
        raise PublishError(
            "Expected exactly one CIV APK from release_build_and_sign; "
            f"found {len(artifacts)}."
        )
    apk = artifacts[0]
    digest = _verify_apk(apk)
    size = apk.stat().st_size

    release_path = f"/repos/{REPOSITORY}/releases/tags/{RELEASE_TAG}"
    status, response = _http(
        opener, "GET", f"{GITHUB_API}{release_path}", token
    )
    if status == 404:
        release = _github_json(
            opener,
            "POST",
            f"/repos/{REPOSITORY}/releases",
            token,
            body={
                "tag_name": RELEASE_TAG,
                "target_commitish": env["CI_COMMIT_SHA"],
                "name": RELEASE_TITLE,
                "body": "Rolling signed CIV APK from the newest successful protected "
                "TAK.gov main pipeline.",
                "draft": True,
                "prerelease": False,
            },
        )
    else:
        release = _json_response(status, response, "GitHub rolling release lookup")
    release_id = release.get("id")
    upload_url = release.get("upload_url")
    if not isinstance(release_id, int) or not isinstance(upload_url, str):
        raise PublishError("GitHub returned an invalid rolling release.")

    candidate_name = (
        f"firecone-candidate-{env['CI_JOB_ID']}-{env['CI_COMMIT_SHORT_SHA']}.apk"
    )
    current_candidate = _asset(opener, release_id, candidate_name, token)
    if current_candidate:
        _validate_uploaded_asset(
            opener, current_candidate, candidate_name, size, digest, token
        )
        candidate = current_candidate
    else:
        upload_parts = urlsplit(upload_url)
        if upload_parts.scheme != "https" or upload_parts.netloc != "uploads.github.com":
            raise PublishError("GitHub returned an unexpected APK upload URL.")
        upload_url = upload_url.split("{", 1)[0]
        upload_query = urlencode({"name": candidate_name})
        status, response = _http(
            opener,
            "POST",
            f"{upload_url}?{upload_query}",
            token,
            binary=apk.read_bytes(),
            content_type="application/vnd.android.package-archive",
        )
        candidate = _json_response(status, response, "GitHub APK upload")
        _validate_uploaded_asset(
            opener, candidate, candidate_name, size, digest, token
        )

    stable = _asset(opener, release_id, STABLE_ASSET_NAME, token)
    backup_name = (
        f"firecone-previous-{env['CI_JOB_ID']}-{env['CI_COMMIT_SHORT_SHA']}.apk"
    )
    old_asset_backed_up = False
    if stable:
        _github_json(
            opener,
            "PATCH",
            f"/repos/{REPOSITORY}/releases/assets/{stable['id']}",
            token,
            body={"name": backup_name},
        )
        old_asset_backed_up = True

    try:
        promoted = _github_json(
            opener,
            "PATCH",
            f"/repos/{REPOSITORY}/releases/assets/{candidate['id']}",
            token,
            body={"name": STABLE_ASSET_NAME},
        )
        _validate_uploaded_asset(
            opener, promoted, STABLE_ASSET_NAME, size, digest, token
        )
    except PublishError:
        if old_asset_backed_up:
            _github_json(
                opener,
                "PATCH",
                f"/repos/{REPOSITORY}/releases/assets/{stable['id']}",
                token,
                body={"name": STABLE_ASSET_NAME},
            )
        raise

    notes = (
        f"Signed CIV APK from TAK.gov pipeline [{env['CI_PIPELINE_ID']}]"
        f"({env['CI_PIPELINE_URL']}) at `{env['CI_COMMIT_SHA']}`.\n\n"
        f"Build job [{env['CI_JOB_ID']}]({env['CI_JOB_URL']}); "
        f"artifact `{apk.name}`; SHA-256 `{digest}`."
    )
    published = _github_json(
        opener,
        "PATCH",
        f"/repos/{REPOSITORY}/releases/{release_id}",
        token,
        body={"name": RELEASE_TITLE, "body": notes, "draft": False, "prerelease": False},
    )
    if (
        published.get("name") != RELEASE_TITLE
        or published.get("draft") is not False
        or published.get("prerelease") is not False
    ):
        raise PublishError("GitHub did not confirm the stable rolling release.")

    _github_json(
        opener,
        "PATCH",
        f"/repos/{REPOSITORY}/git/refs/tags/{RELEASE_TAG}",
        token,
        body={"sha": env["CI_COMMIT_SHA"], "force": True},
    )

    if old_asset_backed_up:
        status, _ = _http(
            opener,
            "DELETE",
            f"{GITHUB_API}/repos/{REPOSITORY}/releases/assets/{stable['id']}",
            token,
        )
        if status < 200 or status >= 300:
            raise PublishError(
                "The new APK is published, but the previous rolling APK "
                f"could not be removed (HTTP {status})."
            )

    print(
        f"Published {STABLE_ASSET_NAME} from pipeline {env['CI_PIPELINE_ID']} "
        f"(SHA-256 {digest})."
    )
    return True


def main() -> int:
    try:
        publish(dict(os.environ))
    except PublishError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
