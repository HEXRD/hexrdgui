# Script that takes the output of git describe --tag and a version component
# string 'full'|'major'|'minor'|'patch' and append the environment variable to
# the env file to set environment variable for that version component to be
# using within the github action workflow.
import sys
import re
import platform
import os

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

# Get the env file
if 'GITHUB_ENV' not in os.environ:
    print('GITHUB_ENV not in environment.')
    sys.exit(3)

github_env = os.environ['GITHUB_ENV']

with open(github_env, 'a') as fp:
    if component == 'full':
        fp.write('VERSION=%s\n' % version)
    elif component == 'major':
        fp.write('VERSION_MAJOR=%s\n' % major)
    elif component == 'minor':
        fp.write('VERSION_MINOR=%s\n' % minor)
    elif component == 'patch':
        fp.write('VERSION_PATCH=%s\n' % patch)
    else:
        print('Invalid version component.')
        sys.exit(4)
