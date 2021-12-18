# -*- mode:python; coding:utf-8; -*-
# author: Mariia Boldyreva <mboldyreva@cloudlinux.com>
# created: 2021-10-28

"""
Hypervisor's stages.
"""

import os
import json
import shutil
import pathlib
import time
from datetime import datetime
from subprocess import PIPE, Popen, STDOUT
from io import BufferedReader
import logging

import requests
import boto3
import ansible_runner

from lib.builder import Builder, ExecuteError
from lib.config import settings


class BaseHypervisor:

    """
    Basic configuration for any hypervisor.
    """

    def __init__(self, name: str, arch: str):
        """
        Basic initialization.

        Parameters
        ----------
        name: str
            Hypervisor name.
        """
        self.name = name
        self.arch = arch
        self._instance_ip = None
        self._instance_id = None
        self.build_number = settings.build_number

    @property
    def terraform_dir(self):
        """
        Gets location of terraform templates for a hypervisor.

        Returns
        -------
        Path
            Path to terraform templates.
        """
        if self.arch == 'aarch64':
            return os.path.join(os.getcwd(), 'terraform/{0}'.format(self.arch))
        else:
            return os.path.join(os.getcwd(), 'terraform/{0}'.format(self.name))

    @property
    def instance_ip(self):
        """
        Gets AWS Instance public ip address.

        Returns
        -------
        str
            AWS Instance public ip address.
        """
        if not self._instance_ip:
            self.get_instance_info()
        return self._instance_ip

    @property
    def instance_id(self):
        """
        Gets AWS Instance id.

        Returns
        -------
        str
            AWS Instance id.
        """
        if not self._instance_id:
            self.get_instance_info()
        return self._instance_id

    def get_instance_info(self):
        """
        Gets AWS Instance information for ssh connections.
        """
        output = Popen(['terraform', 'output', '--json'],
                       cwd=self.terraform_dir, stderr=STDOUT, stdout=PIPE)
        output_json = json.loads(BufferedReader(output.stdout).read().decode())
        self._instance_ip = output_json['instance_public_ip']['value']
        self._instance_id = output_json['instance_id']['value']

    def execute_command(self, cmd: str, cwd_path: str):
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
        logging.info(f'Executing {cmd}')
        proc = Popen(cmd.split(), cwd=cwd_path,
                     stderr=STDOUT, stdout=PIPE)
        for line in proc.stdout:
            logging.info(line.decode())
        proc.wait()
        if proc.returncode != 0:
            raise Exception(
                'Command {0} execution failed {1}'.format(
                    cmd, proc.returncode))

    def create_aws_instance(self):
        """
        Creates AWS Instance using Terraform commands.
        """
        if self.arch == 'aarch64':
            kvm_terraform = os.path.join(os.getcwd(), 'terraform/kvm')
            shutil.copytree(kvm_terraform, self.terraform_dir)
        logging.info('Creating AWS VM')
        terraform_commands = ['terraform init', 'terraform fmt',
                              'terraform validate',
                              'terraform apply --auto-approve']
        for cmd in terraform_commands:
            self.execute_command(cmd, self.terraform_dir)

    def teardown_stage(self):
        """
        Terminates AWS Instance.
        """
        logging.info('Destroying created VM')
        self.execute_command('terraform destroy --auto-approve', self.terraform_dir)
        if self.arch == 'aarch64':
            shutil.rmtree(self.terraform_dir)

    def upload_to_bucket(self, builder: Builder, files: list):
        """
        Upload files to S3 bucket.

        Parameters
        ----------
        builder : Builder
            Builder on AWS Instance.
        files : list
            List of files to upload to S3 bucket.
        """
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Uploading to S3 bucket')
        timestamp_today = str(datetime.date(datetime.today())).replace('-', '')
        timestamp_name = f'{self.build_number}-{self.name}-{timestamp_today}'
        for file in files:
            cmd = f'bash -c "sha256sum {self.cloud_images_path}/{file}"'
            try:
                stdout, _ = ssh.safe_execute(cmd)
            except ExecuteError:
                continue
            checksum = stdout.read().decode().split()[0]
            cmd = f'bash -c "aws s3 cp {self.cloud_images_path}/{file} ' \
                  f's3://{settings.bucket}/{timestamp_name}/ --metadata sha256={checksum}"'
            stdout, _ = ssh.safe_execute(cmd)
            logging.info(stdout.read().decode())
            logging.info('Uploaded')
        ssh.close()
        logging.info('Connection closed')

    def build_stage(self, builder: Builder):
        """
        Executes packer commands to build Vagrant Box.

        Parameters
        ----------
        builder : Builder
            Builder on AWS Instance.
        """
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Packer initialization')
        stdout, _ = ssh.safe_execute('packer init ./cloud-images 2>&1')
        logging.info(stdout.read().decode())
        logging.info('Building vagrant box')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        vb_build_log = f'vagrant_box_build_{timestamp}.log'
        cmd = self.packer_build_cmd.format(vb_build_log)
        try:
            stdout, _ = ssh.safe_execute(cmd)
            sftp = ssh.open_sftp()
            sftp.get(
                f'{self.sftp_path}{vb_build_log}',
                f'{self.name}-{vb_build_log}')
            logging.info(stdout.read().decode())
            logging.info('Vagrant box built')
        finally:
            self.upload_to_bucket(builder, ['vagrant_box_build*.log', '*.box'])
        ssh.close()
        logging.info('Connection closed')

    def release_stage(self, builder: Builder):
        """
        Uploads vagrant box to Vagrant Cloud for the further release.

        Parameters
        ----------
        builder : Builder
            Builder on AWS Instance.
        """
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Creating new version for Vagrant Cloud')
        vagrant_key = settings.vagrant_cloud_access_key
        version = os.environ.get('VERSION')
        changelog = os.environ.get('CHANGELOG')
        cmd = f'bash -c "sha256sum {self.cloud_images_path}/*.box"'
        stdout, _ = ssh.safe_execute(cmd)
        checksum = stdout.read().decode().split()[0]
        data = {'version': version, 'description': changelog}
        data = {'version': data}
        headers = {'Authorization': f'Bearer {vagrant_key}'}
        response = requests.get(
            f'https://app.vagrantup.com/api/v1/box/{settings.vagrant}/version/{version}',
            headers=headers
        )
        if response.status_code == 404:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {vagrant_key}'
            }
            data = f'{json.dumps(data)}'
            response = requests.post(
                f'https://app.vagrantup.com/api/v1/box/{settings.vagrant}/versions',
                headers=headers, data=data
            )
            logging.info(response.content.decode())
        hypervisor = self.name if self.name in ['virtualbox', 'vmware_desktop', 'hyperv'] else 'libvirt'
        logging.info('Preparing for uploading')
        data = {'name': hypervisor, 'checksum_type': 'sha256', 'checksum': checksum}
        data = {'provider': data}

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {vagrant_key}'
        }
        data = f'{json.dumps(data)}'
        response = requests.post(
            f'https://app.vagrantup.com/api/v1/box/{settings.vagrant}/version/{version}/providers',
            headers=headers, data=data
        )
        logging.info(response.content.decode())

        headers = {'Authorization': f'Bearer {vagrant_key}'}
        response = requests.get(
            'https://app.vagrantup.com/api/v1/box/{0}/version/{1}/provider/{2}/upload'.format(
                settings.vagrant, version, hypervisor
            ), headers=headers
        )
        logging.info(response.content.decode())
        upload_path = json.loads(response.content.decode()).get('upload_path')
        logging.info('Uploading the box')
        cmd = f'bash -c "curl {upload_path} --request PUT ' \
              f'--upload-file {self.cloud_images_path}/*.box"'
        stdout, _ = ssh.safe_execute(cmd)
        logging.info(stdout.read().decode())
        ssh.close()
        logging.info('Connection closed')


class LinuxHypervisors(BaseHypervisor):

    """
    Stages for Linux instances.
    """

    cloud_images_path = '/home/ec2-user/cloud-images'
    sftp_path = '/home/ec2-user/cloud-images/'

    def init_stage(self, builder: Builder):
        """
        Creates and provisions AWS Instance.

        Parameters
        ----------
        builder : Builder
            Builder on AWS Instance.
        """
        self.create_aws_instance()
        logging.info('Checking if ready')
        ec2_client = boto3.client(service_name='ec2', region_name='us-east-1')
        waiter = ec2_client.get_waiter('instance_status_ok')
        waiter.wait(InstanceIds=[self.instance_id])
        logging.info('Instance is ready')
        hosts_file = open('./ansible/hosts', 'w')
        lines = ['[aws_instance_public_ip]\n', self.instance_ip, '\n']
        hosts_file.writelines(lines)
        hosts_file.close()

        inv = {
            "aws_instance": {
                "hosts": {
                    self.instance_ip: {
                        "ansible_user": "ec2-user",
                        "ansible_ssh_private_key_file": str(builder.AWS_KEY_PATH.absolute())
                    }
                }
            }
        }
        logging.info('Running Ansible')
        ansible_runner.interface.run(project_dir='./ansible',
                                     playbook='configure_aws_instance.yml',
                                     inventory=inv)

    def test_stage(self, builder: Builder):
        """
        Runs testinfra tests for vagrant box and uploads its log to S3 bucket.

        Parameters
        ----------
        builder : Builder
            Builder on AWS Instance.
        """
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Preparing to test')
        cmd = 'cd /home/ec2-user/cloud-images/ && ' \
              'cp /home/ec2-user/cloud-images/tests/vagrant/Vagrantfile . ' \
              '&& vagrant box add --name almalinux-8-test *.box && vagrant up'
        stdout, _ = ssh.safe_execute(cmd)
        logging.info(stdout.read().decode())
        logging.info('Prepared for test')

        cmd = 'cd /home/ec2-user/cloud-images/ && vagrant ssh-config > .vagrant/ssh-config'
        stdout, _ = ssh.safe_execute(cmd)
        logging.info(stdout.read().decode())

        logging.info('Starting testing')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        vb_test_log = f'vagrant_box_test_{timestamp}.log'

        cmd = f'cd /home/ec2-user/cloud-images/ ' \
              f'&& py.test -v --hosts=almalinux-test-1,almalinux-test-2 --ssh-config=.vagrant/ssh-config' \
              f' /home/ec2-user/cloud-images/tests/vagrant/test_vagrant.py ' \
              f'2>&1 | tee ./{vb_test_log}'

        try:
            stdout, _ = ssh.safe_execute(cmd)
            sftp = ssh.open_sftp()
            sftp.get(
                f'{self.cloud_images_path}/{vb_test_log}',
                f'{self.name}-{vb_test_log}')
            logging.info(stdout.read().decode())
            logging.info('Tested')
        finally:
            self.upload_to_bucket(builder, ['vagrant_box_test*.log'])
        ssh.close()
        logging.info('Connection closed')


class HyperV(BaseHypervisor):

    """
    Stages specified for HyperV hypervisor.
    """

    cloud_images_path = '/mnt/c/Users/Administrator/cloud-images'
    sftp_path = 'c:\\Users\\Administrator\\cloud-images\\'

    packer_build_cmd = (
        'cd c:\\Users\\Administrator\\cloud-images ; '
        'packer build -var hyperv_switch_name=\"HyperV-vSwitch\" '
        '-only=\"hyperv-iso.almalinux-8\" . '
        '| Tee-Object -file c:\\Users\\Administrator\\cloud-images\\{}'
    )

    def __init__(self, arch):
        """
        HyperV initialization.
        """
        super().__init__('hyperv', arch)

    def init_stage(self, builder: Builder):
        """
        Creates and provisions AWS Instance.

        Parameters
        ----------
        builder : Builder
            Builder on AWS Instance.
        """
        self.create_aws_instance()
        logging.info('Checking if ready')
        ec2_client = boto3.client(service_name='ec2', region_name='us-east-1')
        waiter = ec2_client.get_waiter('instance_status_ok')
        waiter.wait(InstanceIds=[self.instance_id])
        logging.info('Instance is ready')

        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        stdout, _ = ssh.safe_execute('git clone https://github.com/AlmaLinux/cloud-images.git')
        logging.info(stdout.read().decode())

        ssh.close()
        logging.info('Connection closed')

    def test_stage(self, builder: Builder):
        """
        Runs testinfra tests for vagrant box and uploads its log to S3 bucket.

        Parameters
        ----------
        builder : Builder
            Builder on AWS Instance.
        """
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Preparing to test')
        cmd = "$Env:SMB_USERNAME = '{0}'; $Env:SMB_PASSWORD='{1}'; " \
              "cd c:\\Users\\Administrator\\cloud-images\\ ; " \
              "cp c:\\Users\\Administrator\\cloud-images\\tests\\vagrant\\Vagrantfile . ; " \
              "vagrant box add --name almalinux-8-test *.box ; vagrant up".format(
                str(os.environ.get('WINDOWS_CREDS_USR')),
                str(os.environ.get('WINDOWS_CREDS_PSW'))
        )
        stdout, _ = ssh.safe_execute(cmd)
        logging.info(stdout.read().decode())

        logging.info('Prepared for test')
        cmd = 'cd c:\\Users\\Administrator\\cloud-images\\ ; ' \
              'vagrant ssh-config | Out-File -Encoding ascii -FilePath .vagrant/ssh-config'
        stdout, _ = ssh.safe_execute(cmd)
        logging.info(stdout.read().decode())

        logging.info('Starting testing')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        vb_test_log = f'vagrant_box_test_{timestamp}.log'
        cmd = f'cd c:\\Users\\Administrator\\cloud-images\\ ; ' \
              f'py.test -v --hosts=almalinux-test-1,almalinux-test-2 --ssh-config=.vagrant/ssh-config ' \
              f'c:\\Users\\Administrator\\cloud-images\\tests\\vagrant\\test_vagrant.py ' \
              f'| Out-File -FilePath c:\\Users\\Administrator\\cloud-images\\{vb_test_log}'
        try:
            stdout, _ = ssh.safe_execute(cmd)
            sftp = ssh.open_sftp()
            sftp.get(
                f'c:\\Users\\Administrator\\cloud-images\\{vb_test_log}',
                f'{self.name}-{vb_test_log}')
            logging.info(stdout.read().decode())
            logging.info('Tested')
        finally:
            self.upload_to_bucket(builder, ['vagrant_box_test*.log'])
        ssh.close()
        logging.info('Connection closed')


class VirtualBox(LinuxHypervisors):

    """
    Specifies VirtualBox hypervisor.
    """

    packer_build_cmd = (
        'cd cloud-images && packer build -only=virtualbox-iso.almalinux-8 . '
        '2>&1 | tee ./{}'
    )

    def __init__(self, arch):
        """
        VirtualBox initialization.
        """
        super().__init__('virtualbox', arch)


class VMWareDesktop(LinuxHypervisors):
    """
    Specifies VMWare Desktop hypervisor.
    """

    packer_build_cmd = (
        'cd cloud-images && packer build -only=vmware-iso.almalinux-8 . '
        '2>&1 | tee ./{}'
    )

    def __init__(self, arch):
        """
        VMWare Desktop initialization.
        """
        super().__init__('vmware_desktop', arch)


class KVM(LinuxHypervisors):
    """
    Specifies KVM hypervisor.
    """

    packer_build_cmd = (
            "cd cloud-images && "
            "packer build -var qemu_binary='/usr/libexec/qemu-kvm' "
            "-only=qemu.almalinux-8 . 2>&1 | tee ./{}"
    )

    def __init__(self, arch, name='kvm'):
        """
        KVM initialization.
        """
        super().__init__(name, arch)

    def build_aws_stage(self, builder: Builder, arch: str):
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Packer initialization')
        stdout, _ = ssh.safe_execute('packer init ./cloud-images 2>&1')
        logging.info(stdout.read().decode())
        logging.info('Building AWS AMI')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        aws_build_log = f'aws_ami_build_{timestamp}.log'
        if arch == 'x86_64':
            logging.info('Building Stage 1')
            cmd = "cd cloud-images && export AWS_DEFAULT_REGION='us-east-1' && " \
                  "export AWS_ACCESS_KEY_ID='{}' && export AWS_SECRET_ACCESS_KEY='{}' " \
                  "&& packer build -var aws_s3_bucket_name='{}' " \
                  "-var qemu_binary='/usr/libexec/qemu-kvm' " \
                  "-var aws_role_name='alma-images-prod-role' " \
                  "-only=qemu.almalinux-8-aws-stage1 . 2>&1 | tee ./{}".format(
                      os.getenv('AWS_ACCESS_KEY_ID'),
                      os.getenv('AWS_SECRET_ACCESS_KEY'),
                      settings.bucket, aws_build_log)
        else:
            cmd = "cd cloud-images && export AWS_DEFAULT_REGION='us-east-1' && " \
                  "export AWS_ACCESS_KEY_ID='{}' && export AWS_SECRET_ACCESS_KEY='{}' " \
                  "&& packer build " \
                  "-only=amazon-ebssurrogate.almalinux-8-aws-aarch64 . " \
                  "2>&1 | tee ./{}".format(
                      os.getenv('AWS_ACCESS_KEY_ID'),
                      os.getenv('AWS_SECRET_ACCESS_KEY'), aws_build_log)
        try:
            stdout, _ = ssh.safe_execute(cmd)
        finally:
            self.upload_to_bucket(builder, ['aws_ami_build_*.log'])
        sftp = ssh.open_sftp()
        sftp.get(
            f'{self.sftp_path}{aws_build_log}',
            f'{self.name}-{aws_build_log}'
        )
        stdout = stdout.read().decode()
        logging.info(stdout)
        ami = None
        for line in stdout.splitlines():
            logging.info(line)
            if line.startswith('us-east-1'):
                ami = line.split(':')[-1].strip()
                logging.info(ami)
        logging.info('AWS AMI built')
        aws_hypervisor = AwsStage2(self.arch)
        tfvars = {'ami_id': ami}
        tf_vars_file = os.path.join(aws_hypervisor.terraform_dir, 'terraform.tfvars.json')
        with open(tf_vars_file, 'w') as tf_file_fd:
            json.dump(tfvars, tf_file_fd)
        cloudinit_script_path = os.path.join(self.cloud_images_path, 'build-tools-on-ec2-userdata.yml')
        sftp.get(
            cloudinit_script_path,
            os.path.join(aws_hypervisor.terraform_dir, 'build-tools-on-ec2-userdata.yml')
        )
        ssh.close()
        logging.info('Connection closed')

    def test_aws_stage(self, builder: Builder):
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        # cmd = 'git clone https://github.com/LKHN/cloud-images.git /home/ec2-user/tests ' \
        #       '&& cd /home/ec2-user/tests && git checkout test-aws-ami'
        # stdout, _ = ssh.safe_execute(cmd)
        arch = self.arch if self.arch == 'aarch64' else 'amd64'
        # cmd = 'sudo chmod 777 -R /home/ec2-user/cloud-images/tests'
        # stdout, _ = ssh.safe_execute(cmd)
        test_path_tf = f'/home/ec2-user/cloud-images/tests/ami/launch_test_instances/{arch}'
        logging.info('Creating test instances')
        cmd = "export AWS_DEFAULT_REGION='us-east-1' && " \
              "export AWS_ACCESS_KEY_ID='{}' && " \
              "export AWS_SECRET_ACCESS_KEY='{}'".format(
                  os.getenv('AWS_ACCESS_KEY_ID'),
                  os.getenv('AWS_SECRET_ACCESS_KEY'))
        # stdout, _ = ssh.safe_execute(cmd)
        terraform_commands = ['terraform init', 'terraform fmt',
                              'terraform validate',
                              f'{cmd} && terraform apply --auto-approve']
        for cmd in terraform_commands:
            # self.execute_command(cmd, test_path_tf)
            stdout, _ = ssh.safe_execute(f'cd {test_path_tf} && {cmd}')
        logging.info('Checking if test instances are ready')
        # add output tf for tests -> implement boto3 waiter
        time.sleep(180)
        logging.info('Test instances are ready')
        logging.info('Starting testing')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        aws_test_log = f'aws_ami_test_{timestamp}.log'
        cmd = f'cd {self.cloud_images_path} && ' \
              f'py.test -v --hosts=almalinux-test-1,almalinux-test-2 ' \
              f'--ssh-config={test_path_tf}/ssh-config ' \
              f'/home/ec2-user/cloud-images/tests/ami/test_ami.py 2>&1 | tee ./{aws_test_log}'
        try:
            stdout, _ = ssh.safe_execute(cmd)
        finally:
            self.upload_to_bucket(builder, ['aws_ami_test*.log'])
        sftp = ssh.open_sftp()
        sftp.get(
            f'{self.cloud_images_path}/{aws_test_log}',
            f'{self.arch}-{aws_test_log}')
        logging.info(stdout.read().decode())
        logging.info('Tested')
        ssh.close()
        logging.info('Connection closed')


class AwsStage2(KVM):

    def __init__(self, arch):
        super().__init__(arch, 'aws-stage-2')

    def init_stage2(self):
        """
        Creates and provisions AWS Instance.
        """
        self.create_aws_instance()
        logging.info('Checking if ready')
        ec2_client = boto3.client(service_name='ec2', region_name='us-east-1')
        waiter = ec2_client.get_waiter('instance_status_ok')
        waiter.wait(InstanceIds=[self.instance_id])
        logging.info('Instance is ready')

    def build_aws_stage(self, builder: Builder, arch: str):
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Packer initialization')
        stdout, _ = ssh.safe_execute('cd /home/ec2-user/cloud-images && sudo packer.io init .')
        logging.info(stdout.read().decode())
        logging.info('Building AWS AMI')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        aws2_build_log = f'aws_ami_stage2_build_{timestamp}.log'
        try:
            stdout, _ = ssh.safe_execute(
                'cd cloud-images && sudo '
                'AWS_ACCESS_KEY_ID="{}" '
                'AWS_SECRET_ACCESS_KEY="{}" '
                'AWS_DEFAULT_REGION="us-east-1" '
                'packer.io build -only=amazon-chroot.almalinux-8-aws-stage2 . 2>&1 | tee ./{}'.format(
                    os.getenv('AWS_ACCESS_KEY_ID'),
                    os.getenv('AWS_SECRET_ACCESS_KEY'),
                    aws2_build_log
                )
            )
        finally:
            pass
            # self.upload_to_bucket(builder, ['aws_ami_stage2_build_*.log'])
        sftp = ssh.open_sftp()
        sftp.get(
            f'{self.sftp_path}{aws2_build_log}',
            f'{self.name}-{aws2_build_log}'
        )
        stdout = stdout.read().decode()
        logging.info(stdout)
        # logging.info(stdout.read().decode())
        ssh.close()
        logging.info('Connection closed')


def get_hypervisor(hypervisor_name, arch='x86_64'):
    """
    Gets specified hypervisor to build a vagrant box.

    Parameters
    ----------
    hypervisor_name: str
        Hypervisor's name.
    arch: str
        Architecture

    Returns
    -------
    Specified Hypervisor.
    """

    return {
        'hyperv': HyperV,
        'virtualbox': VirtualBox,
        'kvm': KVM,
        'vmware_desktop': VMWareDesktop,
        'aws-stage-2': AwsStage2
    }[hypervisor_name](arch)
