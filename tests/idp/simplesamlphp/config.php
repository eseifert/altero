<?php
// Public test configuration, following SimpleSAMLphp's IdP quickstart.
require __DIR__ . '/config.php.dist';
$config = array_replace($config, [
    'baseurlpath' => 'http://localhost:18081/',
    'secretsalt' => 'altero-disposable-test-directory-salt',
    'auth.adminpassword' => 'unused-test-password',
    'enable.saml20-idp' => true,
    'module.enable' => ['exampleauth' => true, 'saml' => true, 'admin' => false],
    'cachedir' => '/tmp/simplesamlphp/cache',
    'logging.handler' => 'errorlog',
    'logging.level' => 4,
    'session.cookie.secure' => false,
    'session.cookie.samesite' => 'Lax',
    'session.phpsession.savepath' => '/tmp/simplesamlphp/sessions',
    'language.default' => 'en',
    'authproc.idp' => [
        10 => ['class' => 'saml:PersistentNameID', 'identifyingAttribute' => 'uid'],
    ],
]);
