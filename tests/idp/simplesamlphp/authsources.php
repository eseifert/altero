<?php
// These credentials are deliberately public fixtures, never real accounts.
$config = [
    'fixture' => [
        'exampleauth:UserPass',
        'users' => [
            'grace:simplesaml-test-password' => [
                'uid' => ['ssp-grace'],
                'preferred_username' => ['grace'],
                'name' => ['Grace Hopper'],
                'email' => ['grace@example.org'],
                'groups' => ['researchers', 'staff'],
            ],
        ],
    ],
];
