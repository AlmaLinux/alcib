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
import requests
import json

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
    headers = {
        'Authorization': f'Bearer {settings.github_token}',
        'Accept': 'application/vnd.github.v3+json',
    }
    data = '{"branch":"master"}'
    response = requests.post(
        'https://api.github.com/repos/VanessaRish/wiki/merge-upstream',
        headers=headers, data=data
    )
    logging.info(response)
    logging.info(response.content)
    logging.info(response.status_code)
    aws_md = os.path.join(os.getcwd(), 'wiki/AWS_AMIS.md')
    md_content = open(aws_md, "r").read()
    md_content = md_content.encode('utf-8')
    md_content = base64.b64encode(md_content)
    md_content = md_content.decode('utf-8')
    response = requests.get(
        'https://api.github.com/repos/VanessaRish/wiki/contents/docs/cloud/AWS_AMIS.md',
        headers=headers)
    sha_md = json.loads(response.content.decode()).get('sha')
    data = f'{{"message":"Updating AWS AMI version in MD file",' \
           f'"content":"{md_content}","sha":"{sha_md}"}}'
    response = requests.put(
        'https://api.github.com/repos/VanessaRish/wiki/contents/docs/cloud/AWS_AMIS.md',
        headers=headers, data=data
    )
    logging.info(response)
    logging.info(response.content)
    logging.info(response.status_code)

    data = '{"head":"VanessaRish:master","base":"master","title":"Updating AWS AMI versions"}'
    response = requests.post(
        'https://api.github.com/repos/AlmaLinux/wiki/pulls',
        headers=headers, data=data
    )
    logging.info(response)
    logging.info(response.content)
    logging.info(response.status_code)


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

    if args.stage == 'pullrequest':
        almalinux_wiki_pr()
    elif args.hypervisor:
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


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
