#!/bin/sh
set -eu
php -r 'exit(PHP_VERSION === "8.4.27" && !ini_get("session.upload_progress.enabled") ? 0 : 1);'
mkdir -p /tmp/simplesamlphp/cache /tmp/simplesamlphp/sessions
openssl req -newkey rsa:3072 -new -x509 -days 2 -nodes \
    -subj /CN=altero-test-idp -out cert/idp.crt -keyout cert/idp.pem
exec php -S 0.0.0.0:8080 -t public
