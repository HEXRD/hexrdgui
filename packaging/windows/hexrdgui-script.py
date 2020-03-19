# -*- coding: utf-8 -*-
import re
import sys
import os
from pathlib import Path

# Start in the bin directory so that everything load OK.
# Start in the bin directory so that everything load OK. Also patch the path so DLL can be found
bin_path = Path(__file__).parent / '..' / 'Library' / 'bin'
os.chdir(bin_path)
os.environ['PATH'] = '%s;%s' % (os.environ['PATH'],  bin_path)

from hexrd.ui.main import main

if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw?|\.exe)?$', '', sys.argv[0])
    sys.exit(main())
