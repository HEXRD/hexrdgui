import json
import logging
import os
from pathlib import Path
import platform
import shutil
import subprocess
import stat
import sys
import tarfile
import tempfile
import zipfile

import click
import coloredlogs

import conda
from conda_build import api as CondaBuild
from conda_build.config import Config
from conda_pack import core as CondaPack

root = logging.getLogger()
root.setLevel(logging.INFO)

logger = logging.getLogger('hexrdgui')
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = coloredlogs.ColoredFormatter('%(asctime)s,%(msecs)03d - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

package_env_name = 'hexrd_package_env'

archive_format = 'zip' if platform.system() == 'Windows' else 'tar'

def run_command(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout

def patch_qt_config(base_path):
    # We could use "qt.conf" instead, but Qt is automatically producing a
    # "qt6.conf" file that overrides ours. Instead of deleting this one,
    # let's just overwrite it...
    logger.info('Patching qt6.conf.')
    with (base_path / 'bin' / 'qt6.conf').open('w') as fp:
        fp.write('[Paths]\n')
        fp.write('Plugins=../lib/qt6/plugins/')

def install_macos_script(base_path, package_path):
   # Add hexrd bash start script
    executable_path = package_path / 'hexrdgui'
    shutil.copyfile(base_path / 'darwin' / 'hexrdgui', executable_path)
    st = os.stat(executable_path)
    os.chmod(executable_path, st.st_mode | stat.S_IXUSR)

def build_mac_app_bundle(base_path, tar_path):
    package_path = base_path / 'package'
    package_path.mkdir()
    hexrd_app_path = package_path / 'HEXRD.app'
    hexrd_app_path.mkdir()
    hexrd_app_contents = hexrd_app_path / 'Contents'
    hexrd_app_contents.mkdir()
    hexrd_app_contents_macos = hexrd_app_contents / 'MacOS'
    hexrd_app_contents_macos.mkdir()
    hexrd_app_contents_resources = hexrd_app_contents / 'Resources'
    hexrd_app_contents_resources.mkdir()

    # Add Info.plist
    shutil.copyfile(base_path / 'darwin' / 'Info.plist', hexrd_app_contents / 'Info.plist')

    # Extract conda-pack tar into Resources/
    logger.info('Extracting tar into Resources/ directory.')
    tar = tarfile.open(tar_path)
    tar.extractall(path=hexrd_app_contents_resources)
    tar.close()

    # Add icon
    shutil.copyfile(base_path / 'darwin' / 'hexrdgui.icns', hexrd_app_contents_resources / 'hexrdgui.icns')

    patch_qt_config(hexrd_app_contents_resources)
    install_macos_script(base_path, hexrd_app_contents_macos)

def install_linux_script(base_path, package_path):
    logger.info('Generating hexrd script.')

    # First we rename the setuptools script
    hexrd_path = package_path / 'bin' / 'hexrdgui'
    hexrdgui_path = package_path / 'bin' / 'run-hexrdgui.py'
    hexrd_path.rename(hexrdgui_path)

    # Now install a shell script to call the setuptools script
    hexrd_executable = str(package_path / 'bin' / 'hexrdgui')
    shutil.copyfile(base_path / 'linux' / 'hexrdgui', hexrd_executable)
    st = os.stat(hexrd_executable)
    os.chmod(hexrd_executable, st.st_mode | stat.S_IXUSR)

def build_linux_package_dir(base_path, tar_path):
    logger.info('Extracting tar into package/ directory.')
    # Now extract the tar into to packge directory so it ready for cpack.
    package_path = base_path / 'package'
    package_path.mkdir(parents=True, exist_ok=True)
    tar = tarfile.open(tar_path)
    tar.extractall(path=package_path)
    tar.close()

    patch_qt_config(package_path)
    install_linux_script(base_path, package_path)

def build_conda_pack(base_path, tmp, hexrd_package_channel, hexrdgui_output_folder):
    # First build the hexrdgui package
    recipe_path = str(base_path / '..' / 'conda.recipe')
    config = Config()
    config.channel_urls = ['conda-forge']

    if hexrdgui_output_folder is not None:
        config.output_folder = hexrdgui_output_folder

    if hexrd_package_channel is not None:
        config.channel_urls.insert(0, hexrd_package_channel)

    # Determine the latest hexrd version in the hexrd_package_channel
    # (release or pre-release), and force that hexrd version to be used.
    cmd = [
        'conda',
        'search',
        '--override-channels',
        '--channel', hexrd_package_channel,
        '--json',
        'hexrd',
    ]
    output = run_command(cmd)
    results = json.loads(output)
    hexrd_version = results['hexrd'][-1]['version']
    config.variant['hexrd_version'] = hexrd_version

    config.CONDA_SOLVER = 'libmamba'
    logger.info('Building hexrdgui conda package.')
    CondaBuild.build(recipe_path, config=config)

    logger.info('Creating new conda environment.')
    # Now create a new environment to install the package into
    env_prefix = str(tmp / package_env_name)

    channels = ['--channel', 'conda-forge']

    # For the mac we need to use our own version of Python built with the
    # latest SDK. See https://github.com/HEXRD/hexrdgui/issues/505 for
    # more details. So we add the HEXRD channel that has our Python package.
    if platform.system() == 'Darwin':
        channels = ['--channel', 'HEXRD'] + channels

    run_command([
        'conda',
        'create',
        '-y',
        '--prefix', env_prefix,
    ])

    hexrdgui_output_folder_uri = Path(hexrdgui_output_folder).absolute().as_uri()

    logger.info('Installing hexrdgui into new environment.')
    # Install hexrdgui into new environment
    cmd = [
        'conda',
        'install',
        '--prefix', env_prefix,
        '--solver', 'libmamba',
        '--override-channels',
        '--channel', hexrdgui_output_folder_uri,
        '--channel', hexrd_package_channel,
        '--channel', 'conda-forge',
        f'hexrd=={hexrd_version}',
        'hexrdgui',
    ]
    run_command(cmd)

    logger.info('Generating tar from environment using conda-pack.')
    # Now use conda-pack to create relocatable archive
    archive_path = str(tmp / ('hexrdgui.%s' % archive_format))
    CondaPack.pack(
        prefix=env_prefix,
        output=archive_path,
        format=archive_format
    )

    return archive_path

# We install a script that ensure the current working directory in
# the bin directory.
def install_windows_script(base_path, package_path):
    logger.info('Patch hexrd script.')

    # Now install a shell script to call the setuptools script
    hexrdgui_script = str(package_path / 'Scripts' / 'hexrdgui-script.py')
    shutil.copyfile(base_path / 'windows' / 'hexrdgui-script.py', hexrdgui_script)

def patch_qt_config_windows(base_path):
    # FIXME: this qt6.conf file appears to be completely ignored.
    # When I try to play with it locally, I cannot get Qt to use it
    # at all, and I don't know why.

    # Until we can get it to read the qt6.conf file, we must copy all
    # plugin directories into the base path.
    plugin_path = base_path / 'Library/lib/qt6/plugins'
    for d in plugin_path.iterdir():
        shutil.move(d, base_path)

    logger.info('Patching qt6.conf.')
    with (base_path / 'qt6.conf').open('w') as fp:
        fp.write('[Paths]\n')
        fp.write('Prefix = Library\n')
        fp.write('Binaries = Library/bin\n')
        fp.write('Libraries = Library/lib\n')
        fp.write('Headers = Library/include/qt\n')
        fp.write('TargetSpec = win32-msvc\n')
        fp.write('HostSpec = win32-msvc\n')
        # FIXME: if Qt starts reading this file, add this line back in
        # and remove the above `shutil.move()` commands.
        # fp.write('Plugins = Library/lib/qt6/plugins\n')

def build_windows_package_dir(base_path, archive_path):
    logger.info('Extracting %s into package/ directory.' % archive_format)
    # Now extract the archive into to packge directory so it ready for cpack.
    package_path = base_path / 'package'
    package_path.mkdir(parents=True, exist_ok=True)
    if archive_format == 'tar':
        tar = tarfile.open(archive_path)
        tar.extractall(path=package_path)
        tar.close()
    else:
        zip_file = zipfile.ZipFile(archive_path)
        zip_file.extractall(path=package_path)
        zip_file.close()

    patch_qt_config_windows(package_path)
    install_windows_script(base_path, package_path)


@click.command()
@click.option('-h', '--hexrd-package-channel', help='the channel to use for HEXRD.')
@click.option('-o', '--hexrdgui-output-folder', type=click.Path(exists=True), help='the path to generate the package into.')
def build_package(hexrd_package_channel, hexrdgui_output_folder):
    tmpdir = None
    try:
        tmp_dir = tempfile.mkdtemp()
        tmp = Path(tmp_dir)
        base_path = Path(__file__).parent
        tar_path = build_conda_pack(base_path, tmp, hexrd_package_channel, hexrdgui_output_folder)

        package_path = base_path / 'package'
        # Remove first so we start fresh
        shutil.rmtree(str(package_path), ignore_errors=True)

        if platform.system() == 'Darwin':
            build_mac_app_bundle(base_path, tar_path)
        elif platform.system() == 'Linux':
            build_linux_package_dir(base_path, tar_path)
        elif platform.system() == 'Windows':
            build_windows_package_dir(base_path, tar_path)
        else:
            raise Exception('Unsupported platform: %s' % platform.system())
    finally:
        if tmp_dir is not None:
            # We run into "Access is denied" when running on Windows in
            # our github worflow, so ignore the errors
            ignore = platform.system() == 'Windows'
            shutil.rmtree(tmp_dir, ignore_errors=ignore)




if __name__ == '__main__':
    build_package()
