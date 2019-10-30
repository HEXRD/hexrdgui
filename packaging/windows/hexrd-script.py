# -*- coding: utf-8 -*-
import re
import sys
import os
from pathlib import Path

# Start in the bin directory so that everything load OK.
os.chdir(Path(__file__).parent / '..' / 'Library' / 'bin')

from hexrd.ui.main import main

if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw?|\.exe)?$', '', sys.argv[0])
    sys.exit(main())
