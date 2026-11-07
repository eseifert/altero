# Checking a rootless Podman deployment

Use this procedure to report a rootless run in [issue #52](https://github.com/eseifert/altero/issues/52).
It exercises SQLite, the web interface, attachment storage, container replacement
and the image's health check. The [recorded run below](#recorded-run) passes with
the published beta.7 image. PostgreSQL, Compose and systemd integration need
separate reports.

Use a Linux account with [rootless Podman already configured](https://docs.podman.io/en/stable/markdown/podman.1.html#rootless-mode),
a browser and curl. Run the following blocks in the same shell, stopping on any
failure. Use a new container and volume name for each attempt so a failed run's
data remains available for inspection.

## Record the host and image

```sh
podman version
podman info --format '{{.Host.Security.Rootless}}'
podman info --format '{{.Store.GraphDriverName}}'

altero_probe_image=ghcr.io/eseifert/altero:1.0.0-beta.7
altero_probe_name=altero-rootless-check
altero_probe_volume=altero-rootless-check-data
altero_probe_port=18080
altero_probe_url="http://127.0.0.1:${altero_probe_port}"

podman pull "$altero_probe_image"
podman image inspect --format '{{.Id}} {{.Digest}} {{.Config.User}}' "$altero_probe_image"
```

The rootless field must be `true`. Run these commands as the ordinary account
that will own the containers. [Podman info](https://docs.podman.io/en/stable/markdown/podman-info.1.html)
also records the host, storage driver and namespace mappings if setup fails.
Record the image ID and digest: a report about another image does not establish
that a newer build works. For a source build, use the [Docker image format](deployment.md#podman)
and record its commit and image ID.

## Start with a new volume

```sh
podman volume create "$altero_probe_volume"
podman run --detach --name "$altero_probe_name" \
  --publish "127.0.0.1:${altero_probe_port}:8000" \
  --volume "${altero_probe_volume}:/data" \
  "$altero_probe_image"

curl --fail --retry 60 --retry-all-errors --retry-delay 2 --retry-max-time 180 \
  --max-time 5 "$altero_probe_url/health"
curl --fail --output /dev/null "$altero_probe_url/app/"
podman exec "$altero_probe_name" id -u
podman healthcheck run "$altero_probe_name"
```

The readiness request retries for up to three minutes, including connection
resets while migrations and server startup finish. The process UID must be
`10001`, and the health check must exit with code `0`.
A fresh named volume lets Podman initialise the mount's ownership for the image
user; see [volume ownership](https://docs.podman.io/en/stable/markdown/podman-run.1.html).
If the check fails, preserve `podman logs` and inspect the health-check state
using [Podman's health-check commands](https://docs.podman.io/en/stable/markdown/podman-healthcheck.1.html).

Create a disposable account and set its password interactively:

```sh
podman exec -it "$altero_probe_name" altero user add podmancheck
podman exec -it "$altero_probe_name" altero user password podmancheck
```

Open `http://127.0.0.1:18080/app/` (using your selected host port) and sign in. In the
[web library](web/library.md), create a book, add a note with recognisable text
and attach a small local file. Download the attachment and compare its SHA-256
with the original. Keep the original file and the expected digest for the next
step. Successful attachment upload checks that the application's mapped user
can write the storage directory.

## Replace the container and change its internal port

Keep the volume while removing only the disposable container. Start its
replacement with the same image and volume but internal port `8091`:

```sh
podman stop "$altero_probe_name"
podman rm "$altero_probe_name"
podman run --detach --name "$altero_probe_name" \
  --env ALTERO_PORT=8091 \
  --publish "127.0.0.1:${altero_probe_port}:8091" \
  --volume "${altero_probe_volume}:/data" \
  "$altero_probe_image"

curl --fail --retry 60 --retry-all-errors --retry-delay 2 --retry-max-time 180 \
  --max-time 5 "$altero_probe_url/health"
podman healthcheck run "$altero_probe_name"
podman exec "$altero_probe_name" id -u
```

The health check must again succeed, and the UID must still be `10001`.
Sign in again, check that the book and note survived, and download the same
attachment. Its digest must still match the original. This checks persistence
across container replacement as well as the health check's configured port.

## Report the result

Include the date, distribution and kernel, Podman version, rootless result,
storage driver, image ID/digest, and whether each step passed. Say that this was
a named-volume SQLite run. Report bind mounts, PostgreSQL, Compose or Quadlet
separately, with their configuration differences.

Keep failed runs and their logs for diagnosis. Remove passwords, API keys,
cookies and storage tokens before sharing logs. After a successful report, the
disposable container and volume can be removed explicitly:

```sh
podman stop "$altero_probe_name"
podman rm "$altero_probe_name"
podman volume rm "$altero_probe_volume"
```

## Recorded run

On 2026-11-08, the published `ghcr.io/eseifert/altero:1.0.0-beta.7` image
passed this procedure on Linux amd64 with a fresh named volume and SQLite.
The image's source revision label is `920a388d75d798b01daca2cbbe77360c87112a68`.

| Component | Recorded value |
| --- | --- |
| Host | Gentoo, kernel `7.3.1-gentoo` |
| Podman | `6.1.4`, rootless `true` |
| Storage | `overlay` on Btrfs |
| Runtime | crun `1.28`, cgroup v2, systemd cgroup manager |
| Networking | Netavark with pasta; published only on `127.0.0.1:18080` |
| Process and volume ownership | UID `10001`, GID `999` |
| Browser | Playwright driving Chromium `156.0.8078.4`, English, 1280 × 900 |

The pulled image has these identifiers; the digest identifies the local amd64
manifest, and the image ID identifies its configuration:

```text
digest:   sha256:51221f15ed2705f91e76bf77f37e239eda979943c3a971b8c36a84e045f0db2a
image ID: sha256:857df51409e3cefb43be8526ecf7cba4a23caea319151d619341453d665f4b0a
```

| Check | Result |
| --- | --- |
| Fresh startup | Migrations complete; `/health` returns 200 and beta.7/schema 42 |
| Image health check | Exit 0 and `healthy` on both internal ports, 8000 and 8091 |
| Browser writes | CLI-created account signs in; browser creates a book and child note, then uploads a text attachment |
| Initial download | Browser Download returns the original bytes |
| Container replacement | Original container removed; same image and named volume started with `ALTERO_PORT=8091` |
| Persistent state | Fresh browser session signs in; book, note and attachment retain their keys, versions and data |
| Persistent file | Second browser download matches the original bytes and SHA-256 |
| Browser runtime | No page errors or CSP violations observed in either session; screenshots inspected |

Both downloads have SHA-256:

```text
3bd3eb08b50d93442102e4fd0b5fb27c2768984a4078485e8e8fd6353412220f
```

Startup produced temporary connection resets, and the original 20-retry check
also expired during replacement under host load. The procedure above now retries
resets and allows up to three minutes. Successful health checks were recorded
after readiness; this is no startup-time or performance guarantee.

This result covers the published amd64 image and a named-volume SQLite
deployment. Source builds, bind mounts, SELinux labelling (disabled on this
host), PostgreSQL, Compose, Quadlet and other architectures need separate
evidence. It does not extend desktop sync acceptance coverage.
