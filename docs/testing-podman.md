# Checking a rootless Podman deployment

Use this procedure to report a rootless run in [issue #52](https://github.com/eseifert/altero/issues/52).
It exercises SQLite, the web interface, attachment storage, container replacement
and the image's health check. PostgreSQL, Compose and systemd integration need
separate reports. This procedure is prepared for operators; a passing run is
still needed.

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

curl --fail --retry 20 --retry-connrefused --retry-delay 1 "$altero_probe_url/health"
curl --fail --output /dev/null "$altero_probe_url/app/"
podman exec "$altero_probe_name" id -u
podman healthcheck run "$altero_probe_name"
```

The process UID must be `10001`, and the health check must exit with code `0`.
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

curl --fail --retry 20 --retry-connrefused --retry-delay 1 "$altero_probe_url/health"
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
