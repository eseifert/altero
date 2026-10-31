# Test-only IdP. PHP 8.4.27 fixes CVE-2026-109618 and CVE-2026-109619.
FROM php:8.4.27-cli@sha256:7e7413ed31b8c42b31c939cc83b3758b1cd618f7bf3803f5a0c39f98d4adcbee

# The full upstream release includes its locked dependencies and built assets.
ADD --checksum=sha256:b199ebcba6e30220e7b5df2783ca42f8947dd9bdf046e9e6302fef3d3a438d01 \
    https://github.com/simplesamlphp/simplesamlphp/releases/download/v2.5.3.1/simplesamlphp-2.5.3.1-full.tar.gz /tmp/simplesamlphp.tar.gz
RUN mkdir /srv/simplesamlphp \
    && tar -xzf /tmp/simplesamlphp.tar.gz -C /srv/simplesamlphp --strip-components=1 \
    && rm /tmp/simplesamlphp.tar.gz \
    && php -r 'exit(PHP_VERSION === "8.4.27" ? 0 : 1);'

WORKDIR /srv/simplesamlphp
COPY php.ini /usr/local/etc/php/conf.d/altero-test.ini
COPY config.php authsources.php config/
COPY saml20-idp-hosted.php saml20-sp-remote.php metadata/
COPY health.php public/health.php
COPY start.sh /usr/local/bin/start-simplesamlphp
CMD ["sh", "/usr/local/bin/start-simplesamlphp"]
