<?php
// Readiness includes the generated certificate and the actual PHP runtime.
http_response_code(503);
require dirname(__DIR__) . '/vendor/autoload.php';
$version = ltrim(\Composer\InstalledVersions::getPrettyVersion('simplesamlphp/simplesamlphp'), 'v');
$ready = PHP_VERSION === '8.4.27'
    && !ini_get('session.upload_progress.enabled')
    && $version === '2.5.3.1'
    && is_file(dirname(__DIR__) . '/cert/idp.crt');
http_response_code($ready ? 200 : 503);
header('Content-Type: application/json');
echo json_encode([
    'phpVersion' => PHP_VERSION,
    'simplesamlphpVersion' => $version,
    'sessionUploadProgressEnabled' => (bool) ini_get('session.upload_progress.enabled'),
]);
