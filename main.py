# -*- mode:python; coding:utf-8; -*-
# author: Mariia Boldyreva <mboldyreva@cloudlinux.com>
# created: 2021-10-28

"""
Script for building Vagrant Boxes.
"""

import sys
import argparse
import logging
import os
import base64
import hashlib

from lib.builder import Builder
from lib.hypervisors import get_hypervisor, execute_command
from lib.config import settings


def init_args_parser() -> argparse.ArgumentParser:
    """
    Command line arguments parser initialization.

    Returns
    -------
    argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description='Cloud Images autobuilder'
    )
    parser.add_argument('--hypervisor', type=str,
                        choices=['VirtualBox', 'KVM', 'VMWare_Desktop', 'HyperV',
                                 'AWS-STAGE-2', 'Equinix'],
                        help='Hypervisor name', required=False)
    parser.add_argument('--stage', type=str,
                        choices=['init', 'build', 'destroy',
                                 'test', 'release', 'pullrequest'],
                        help='Stage')
    parser.add_argument('--arch', type=str, choices=['x86_64', 'aarch64'],
                        help='Architecture', required=False)
    return parser


def almalinux_wiki_pr():
    cmd = f'curl -X POST -H "Authorization: token {settings.github}" ' \
          f'-H "Accept: application/vnd.github.v3+json" ' \
          f'https://api.github.com/repos/VanessaRish/wiki/merge-upstream ' \
          f'-d \'{"branch":"master"}\''
    path = os.path.join(os.getcwd(), 'wiki/')
    execute_command(cmd, path)
    aws_csv = os.path.join(os.getcwd(), 'wiki/aws_amis.csv')
    aws_md = os.path.join(os.getcwd(), 'wiki/AWS_AMIS.md')
    csv_content = base64.b64encode(open(aws_csv, "rb").read())
    md_content = base64.b64encode(open(aws_md, "rb").read())
    sha256_hash_csv = hashlib.sha256()
    sha256_hash_md = hashlib.sha256()
    with open(aws_md, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash_md.update(byte_block)
        sha_md = sha256_hash_md.hexdigest()
    with open(aws_csv, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash_csv.update(byte_block)
        sha_csv = sha256_hash_csv.hexdigest()

    cmd = f'curl -X POST -H "Authorization: token {settings.github}" ' \
          f'-H "Accept: application/vnd.github.v3+json" ' \
          f'https://api.github.com/repos/VanessaRish/wiki/docs/cloud/AWS_AMIS.md  ' \
          f'-d \'{"message":"Updating AWS AMI version in MD file","content":"{md_content}","sha":"{sha_md}"}\''
    execute_command(cmd, path)

    cmd = f'curl -X POST -H "Authorization: token {settings.github}" ' \
          f'-H "Accept: application/vnd.github.v3+json" ' \
          f'https://api.github.com/repos/VanessaRish/wiki/docs/cloud/aws_amis.csv  ' \
          f'-d \'{"message":"Updating AWS AMI version in CSV file","content":"{csv_content}","sha":"{sha_csv}"}\''
    execute_command(cmd, path)

    cmd = f'curl -X POST -H "Authorization: token {settings.github}" ' \
          f'-H "Accept: application/vnd.github.v3+json" ' \
          f'https://api.github.com/repos/VanessaRish/wiki/pulls  ' \
          f'-d \'{"head":"master","base":"master","title":"Updating AWS AMI versions"}\''
    execute_command(cmd, path)


def setup_logger():
    """
    Setup for logger.
    """
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    log_format = "%(asctime)s %(levelname)-8s [%(threadName)s]: %(message)s"
    formatter = logging.Formatter(log_format, '%y.%m.%d %H:%M:%S')
    handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main(sys_args):
    """
    Executes stages to build, test and release Vagrant Box.
    """
    args_parser = init_args_parser()
    args = args_parser.parse_args(sys_args)

    setup_logger()
    builder = Builder()

    if args.arch == 'aarch64':
        hypervisor = get_hypervisor(args.hypervisor.lower(), args.arch)
    else:
        hypervisor = get_hypervisor(args.hypervisor.lower())

    if args.stage == 'init':
        hypervisor.init_stage(builder)
    elif args.stage == 'build' and settings.image in ['Vagrant Box', 'Generic Cloud']:
        hypervisor.build_stage(builder)
    elif args.stage == 'build' and settings.image == 'AWS AMI' and args.hypervisor != 'AWS-STAGE-2':
        hypervisor.build_aws_stage(builder, args.arch)
    elif args.stage == 'test':
        if settings.image == 'AWS AMI':
            hypervisor.test_aws_stage(builder)
        elif settings.image == 'Generic Cloud':
            hypervisor.test_openstack(builder)
        else:
            hypervisor.test_stage(builder)
    elif args.stage == 'release':
        if settings.image in ['OpenNebula', 'Generic Cloud']:
            hypervisor.release_and_sign_stage(builder)
        elif settings.image == 'AWS AMI':
            hypervisor.publish_ami(builder)
        else:
            hypervisor.release_stage(builder)
    elif args.stage == 'destroy':
        if settings.image == 'Generic Cloud' and args.arch == 'aarch64':
            hypervisor.teardown_equinix_stage(builder)
        else:
            hypervisor.teardown_stage()
    elif args.hypervisor == 'AWS-STAGE-2' and args.stage != 'destroy':
        hypervisor.init_stage(builder)
        hypervisor.build_aws_stage(builder, args.arch)
    elif args.stage == 'pullrequest':
        almalinux_wiki_pr()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
