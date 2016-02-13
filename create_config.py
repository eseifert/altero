#!/bin/env python
# -*- coding: utf-8 -*-
import os


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG_FILENAME = 'config.py'


with open(os.path.join(BASE_DIR, CONFIG_FILENAME), 'w') as config:
    config.write("""\
# -*- coding: utf-8 -*-
""")
    print('Successfully created %s' % CONFIG_FILENAME)
