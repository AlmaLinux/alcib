# -*- mode:python; coding:utf-8; -*-
# author: Mariia Boldyreva <mboldyreva@cloudlinux.com>
# created: 2021-10-28

"""
Helping functions.
"""

import collections
import logging
import json
import re
import requests
from subprocess import PIPE, Popen, STDOUT

from jinja2 import DictLoader, Environment

from lib.config import settings


Package = collections.namedtuple(
    'rpm_package', ['name', 'version', 'release', 'arch', 'clean_release']
)


__all__ = ['save_ami_id', 'parse_package', 'execute_command',
           'sftp_download', 'get_git_branches', 'generate_clouds']


def save_ami_id(stdout, arch: str) -> str:
    """Saves AMI's id in a file on Jenkins node."""
    ami = None
    for line in stdout.splitlines():
        logging.info(line)
        if line.startswith('us-east-1'):
            ami = line.split(':')[-1].strip()
    with open(f'ami_id_{arch}.txt', 'w') as ami_file:
        ami_file.write(ami)
    logging.info('AWS AMI %s built', ami)
    return ami


def parse_package(package):
    package = package.rstrip('.rpm')
    dot = package.rfind('.')
    package, arch = package[:dot], package[dot + 1:]
    dash = package.rfind('-')
    package, release = package[:dash], package[dash + 1:]
    dash = package.rfind('-')
    name, version = package[:dash], package[dash + 1:]
    clean_release = re.sub('\.el\d*', '', release)
    return Package(name, version, release, arch, clean_release)


def execute_command(cmd: str, cwd_path: str):
    """
    Executes a local command.

    Parameters
    ----------
    cmd : str
        A command to execute.
    cwd_path: str
        Directory path to execute commands.

    Raises
    ------
    Exception
        If a command fails during execution.
    """
    logging.info('Executing %s', cmd)
    proc = Popen(cmd.split(), cwd=cwd_path, stderr=STDOUT, stdout=PIPE)
    for line in proc.stdout:
        logging.info(line.decode())
    proc.wait()
    if proc.returncode != 0:
        raise Exception('Command {0} execution failed {1}'.format(
            cmd, proc.returncode
        ))


def sftp_download(ssh, path, file, name):
    sftp = ssh.open_sftp()
    sftp.get(f'{path}/{file}', f'{name}-{file}')


def get_git_branches(headers, repo):
    branch_regex = r'^al-\d\.\d\.\d-\d{8}$'
    response = requests.get(f'{repo}/branches', headers=headers)
    branches = []
    for item in json.loads(response.content.decode()):
        res = re.search(branch_regex, item['name'])
        if res:
            branches.append(item['name'])
    branches.sort()
    return branches


def generate_clouds(yaml_template) -> str:
    """
    Generates clouds.yaml
    """
    env = Environment(loader=DictLoader({'clouds': yaml_template}))
    template = env.get_template('clouds')
    return template.render(config=settings)
