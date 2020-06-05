# Script that takes the output of git describe --tag and a version component string
# 'full'|'major'|'minor'|'patch' and spits out the appropriate ::set-env commands
# to set environment variable for that version component to be using
# within the github action workflow.
import sys
import re
import platform

if len(sys.argv) != 3:
    print('Please provide version string and component.')
    sys.exit(1)

version = sys.argv[1]
component = sys.argv[2]
version_regex = re.compile(r'v?([0-9]*)\.([0-9]*)\.(.*)')


match = version_regex.match(version)
if match is None:
    print('Invalid version string.')
    sys.exit(2)

major = match.group(1)
minor = match.group(2)
patch = match.group(3)
version = '%s.%s.%s' % (major, minor, patch)

# Windows only allows 0 to 65534 in version string, we have to parse it further
if platform.system() == 'Windows':
    parts = patch.split('-')
    # If we are not on a tag
    if len(parts) == 3:
        patch = parts[0]
        build = parts[1]
        version = '%s.%s.%s.%s' % (major, minor, patch, build)

if component == 'full':
    print('::set-env name=VERSION::%s' % version)
elif component  == 'major':
    print('::set-env name=VERSION_MAJOR::%s' % major)
elif component == 'minor':
    print('::set-env name=VERSION_MINOR::%s' % minor)
elif component == 'patch':
    print('::set-env name=VERSION_PATCH::%s' % patch)
else:
    print('Invalid version component.')
    sys.exit(3)



