#!/usr/bin/env python3
'''run skel from a checkout without installing it'''

import sys

from skel import main
if '__main__' == __name__:
    sys.exit(main())
