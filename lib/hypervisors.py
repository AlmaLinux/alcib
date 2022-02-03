# -*- mode:python; coding:utf-8; -*-
# author: Mariia Boldyreva <mboldyreva@cloudlinux.com>
# created: 2021-10-28

"""
Hypervisor's stages.
"""

import os
import json
import shutil
from datetime import datetime
from subprocess import PIPE, Popen, STDOUT
from io import BufferedReader
import logging
import time

import requests
import boto3
from jinja2 import DictLoader, Environment
import ansible_runner

from lib.builder import Builder, ExecuteError
from lib.config import settings


def download_qcow(arch, builder, instance_ip, name, path):
    timestamp = str(datetime.date(datetime.today())).replace('-', '')
    qcow_name = f'AlmaLinux-8-GenericCloud-8.5.{arch}.qcow2'
    qcow_tm_name = f'AlmaLinux-8-GenericCloud-8.5-{timestamp}.{arch}.qcow2'
    # ftp_path = f'/var/ftp/pub/cloudlinux/almalinux/8/cloud/{arch}}'
    ssh_aws = builder.ssh_aws_connect(instance_ip, name)
    sftp = ssh_aws.open_sftp()
    sftp.get(
        f'{path}/{qcow_name}', f'{qcow_tm_name}'
    )


def koji_release(ftp_path, qcow_name, builder):
    ssh_koji = builder.ssh_koji_connect()
    stdout, _ = ssh_koji.safe_execute(
        f'ln -sf {ftp_path}/images/{qcow_name} '
        f'{ftp_path}/AlmaLinux-8-GenericCloud-latest.x86_64.qcow2'
    )
    logging.info(stdout.read().decode())
    stdout, _ = ssh_koji.safe_execute('sha256sum *.qcow2 > CHECKSUM')
    logging.info(stdout.read().decode())
    stdout, _ = ssh_koji.safe_execute(
        f'rsync --dry-run -avSHP {ftp_path} deploy-repo-alma@192.168.246.161:/repo/almalinux/8/cloud/'
    )
    logging.info(stdout.read().decode())
    stdout, _ = ssh_koji.safe_execute(
        f'rsync -avSHP {ftp_path} deploy-repo-alma@192.168.246.161:/repo/almalinux/8/cloud/'
    )
    logging.info(stdout.read().decode())

    ssh_deploy = builder.ssh_deploy_connect()
    stdout, _ = ssh_deploy.safe_execute('systemctl start --no-block rsync-repo-alma')
    logging.info(stdout.read().decode())
    ssh_deploy.close()
    ssh_koji.close()


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
            execute_command(cmd, self.terraform_dir)

    def teardown_stage(self):
        """
        Terminates AWS Instance.
        """
        logging.info('Destroying created VM')
        execute_command('terraform destroy --auto-approve', self.terraform_dir)
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
        timestamp_name = f'{self.build_number}-{settings.image.replace(" ", "_")}-{self.name}-{self.arch}-{timestamp_today}'
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
        logging.info(f'Building {settings.image}')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        vb_build_log = f'{settings.image.replace(" ", "_")}_{self.arch}_build_{timestamp}.log'
        if settings.image == 'Generic Cloud':
            cmd = self.packer_build_gencloud.format(vb_build_log)
        else:
            cmd = self.packer_build_cmd.format(vb_build_log)
        try:
            stdout, _ = ssh.safe_execute(cmd)
            sftp = ssh.open_sftp()
            sftp.get(
                f'{self.sftp_path}{vb_build_log}',
                f'{self.name}-{vb_build_log}')
            logging.info(stdout.read().decode())
            logging.info(f'{settings.image} built')
        finally:
            if settings.image == 'Generic Cloud':
                file = 'output-almalinux-8-gencloud-x86_64/*.qcow2'
            else:
                file = '*.box'
            self.upload_to_bucket(
                builder,
                [f'{settings.image.replace(" ", "_")}_{self.arch}_build*.log', file]
            )
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
              f'&& py.test -v --hosts=almalinux-test-1,almalinux-test-2 ' \
              f'--ssh-config=.vagrant/ssh-config' \
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
              f'py.test -v --hosts=almalinux-test-1,almalinux-test-2 ' \
              f'--ssh-config=.vagrant/ssh-config ' \
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

    packer_build_gencloud = (
        "cd cloud-images && "
        "packer build -var qemu_binary='/usr/libexec/qemu-kvm'"
        " -only=qemu.almalinux-8-gencloud-x86_64 . 2>&1 | tee ./{}"
    )

    def __init__(self, name='kvm', arch='x86_64'):
        """
        KVM initialization.
        """
        super().__init__(name, arch)

    def publish_ami(self, builder: Builder):
        ami_id = None
        with open(f'ami_id_{self.arch}.txt', 'r') as f:
            ami_id = f.read()
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Preparing csv and md')
        cmd = "cd /home/ec2-user/cloud-images/ && " \
              "export AWS_DEFAULT_REGION='us-east-1' && " \
              "export AWS_ACCESS_KEY_ID='{}' " \
              "&& export AWS_SECRET_ACCESS_KEY='{}' " \
              "&& /home/ec2-user/cloud-images/bin/aws_ami_mirror.py " \
              "-a {} --csv-output aws_amis-{}.csv " \
              "--md-output AWS_AMIS-{}.md --verbose".format(
                  os.getenv('AWS_ACCESS_KEY_ID'),
                  os.getenv('AWS_SECRET_ACCESS_KEY'),
                  ami_id, self.arch, self.arch)
        stdout, _ = ssh.safe_execute(cmd)
        logging.info(stdout.read().decode())
        self.upload_to_bucket(builder, ['aws_amis*.csv', 'AWS_AMIS*.md'])
        sftp = ssh.open_sftp()
        sftp.get(
            f'{self.sftp_path}/aws_amis-{self.arch}.csv',
            f'aws_amis-{self.arch}.csv'
        )
        sftp.get(
            f'{self.sftp_path}/AWS_AMIS-{self.arch}.md',
            f'AWS_AMIS-{self.arch}.md'
        )

        ssh.close()

    def release_and_sign_stage(self, builder: Builder):
        download_qcow(self.arch, builder, self.instance_ip, self.name, self.sftp_path)
        # timestamp = str(datetime.date(datetime.today())).replace('-', '')
        # qcow_name = f'AlmaLinux-8-GenericCloud-8.5.aarch64.qcow2'
        # qcow_tm_name = f'AlmaLinux-8-GenericCloud-8.5-{timestamp}.aarch64.qcow2'
        # ftp_path = '/var/ftp/pub/cloudlinux/almalinux/8/cloud/aarch64'
        # ssh_aws = builder.ssh_aws_connect(self.instance_ip, self.name)
        # sftp = ssh_aws.open_sftp()
        # sftp.get(
        #     f'{self.sftp_path}/{qcow_name}',
        #     f'{qcow_tm_name}'
        # )
        # proc = Popen(cmd.split(), cwd=cwd_path,
        #              stderr=STDOUT, stdout=PIPE)
        # for line in proc.stdout:
        #     logging.info(line.decode())
        # proc.wait()
        # stdout, _ = ssh_aws.safe_execute(
        #     f'scp /home/ec2-user/cloud-images/*.qcow2 '
        #     f'mockbuild@192.168.246.161:{ftp_path}/images/{qcow_name}'
        # )
        # logging.info(stdout.read().decode())
        # koji_release(ftp_path, qcow_name, builder)
        # ssh_aws.close()

    def build_aws_stage(self, builder: Builder, arch: str):
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Packer initialization')
        stdout, _ = ssh.safe_execute('packer init ./cloud-images 2>&1')
        logging.info(stdout.read().decode())
        logging.info('Building AWS AMI')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        aws_build_log = f'aws_ami_build_{self.arch}_{timestamp}.log'
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
            self.upload_to_bucket(builder, ['aws_ami_build*.log'])
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
        with open(f'ami_id_{self.arch}.txt', 'w') as f:
            f.write(ami)
        logging.info('AWS AMI built')
        aws_hypervisor = AwsStage2(self.arch)
        tfvars = {'ami_id': ami}
        tf_vars_file = os.path.join(aws_hypervisor.terraform_dir,
                                    'terraform.tfvars.json')
        with open(tf_vars_file, 'w') as tf_file_fd:
            json.dump(tfvars, tf_file_fd)
        cloudinit_script_path = os.path.join(
            self.cloud_images_path, 'build-tools-on-ec2-userdata.yml'
        )
        sftp.get(
            cloudinit_script_path,
            os.path.join(
                aws_hypervisor.terraform_dir, 'build-tools-on-ec2-userdata.yml'
            )
        )
        ssh.close()
        logging.info('Connection closed')

    def test_aws_stage(self, builder: Builder):
        """
        builder: Builder
            Main builder configuration.

        Runs Testinfra tests for AWS AMI.
        """
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        sftp = ssh.open_sftp()
        sftp.put(str(builder.AWS_KEY_PATH.absolute()),
                 '/home/ec2-user/.ssh/alcib_rsa4096')

        cmd = 'sudo chmod 700 /home/ec2-user/.ssh && ' \
              'sudo chmod 600 /home/ec2-user/.ssh/alcib_rsa4096'
        stdout, _ = ssh.safe_execute(cmd)

        arch = self.arch if self.arch == 'aarch64' else 'amd64'
        test_path_tf = f'/home/ec2-user/cloud-images/tests/ami/launch_test_instances/{arch}'
        logging.info('Creating test instances')
        cmd_export = \
            "export AWS_DEFAULT_REGION='us-east-1' && " \
            "export AWS_ACCESS_KEY_ID='{}' && " \
            "export AWS_SECRET_ACCESS_KEY='{}'".format(
                os.getenv('AWS_ACCESS_KEY_ID'),
                os.getenv('AWS_SECRET_ACCESS_KEY'))
        terraform_commands = ['terraform init', 'terraform fmt',
                              'terraform validate',
                              f'{cmd_export} && terraform apply --auto-approve']
        for command in terraform_commands:
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf} && {command}'
            )
            logging.info(stdout.read().decode())
        logging.info('Checking if test instances are ready')
        output_cmd = f'cd {test_path_tf} && {cmd_export} && terraform output --json'
        stdout, _ = ssh.safe_execute(output_cmd)
        output = stdout.read().decode()
        logging.info(output)
        output_json = json.loads(output)

        instance_id1 = output_json['instance_id1']['value']
        instance_id2 = output_json['instance_id2']['value']
        ec2_client = boto3.client(service_name='ec2', region_name='us-east-1')
        waiter = ec2_client.get_waiter('instance_status_ok')
        waiter.wait(InstanceIds=[instance_id1, instance_id2])

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
            logging.info(stdout.read().decode())
        finally:
            self.upload_to_bucket(builder, ['aws_ami_test*.log'])
            logging.info(stdout.read().decode())

        sftp.get(
            f'{self.cloud_images_path}/{aws_test_log}',
            f'{self.arch}-{aws_test_log}')
        logging.info(stdout.read().decode())
        logging.info('Tested')
        stdout, _ = ssh.safe_execute(
            f'cd {test_path_tf} && {cmd_export} && '
            f'terraform destroy --auto-approve'
        )
        ssh.close()
        logging.info('Connection closed')

    def test_openstack(self, builder: Builder):
        """
        builder: Builder
            Main Builder Configuration.

        Runs Testinfra tests for the built openstack image.
        """
        yaml = os.path.join(os.getcwd(), 'clouds.yaml.j2')
        content = open(yaml, 'r').read()
        yaml_content = generate_clouds(content)

        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        sftp = ssh.open_sftp()
        stdout, _ = ssh.safe_execute('mkdir -p /home/ec2-user/.config/openstack/')

        sftp.put(str(builder.AWS_KEY_PATH.absolute()), '/home/ec2-user/.ssh/alcib_rsa4096')

        cmd = 'sudo chmod 700 /home/ec2-user/.ssh && ' \
              'sudo chmod 600 /home/ec2-user/.ssh/alcib_rsa4096'
        stdout, _ = ssh.safe_execute(cmd)

        yaml_file = sftp.file('/home/ec2-user/.config/openstack/clouds.yaml', "w")
        yaml_file.write(yaml_content)
        yaml_file.flush()

        arch = self.arch if self.arch == 'aarch64' else 'amd64'
        test_path_tf = '/home/ec2-user/cloud-images/tests/genericcloud'
        logging.info('Uploading openstack image')

        stdout, _ = ssh.safe_execute(
            f'cp '
            f'/home/ec2-user/cloud-images/output-almalinux-8-gencloud-x86_64/*.qcow2 '
            f'{test_path_tf}/upload_image/{arch}/')
        terraform_commands = ['terraform init', 'terraform fmt',
                              'terraform validate',
                              'terraform apply --auto-approve']
        for command in terraform_commands:
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/upload_image/{arch}/ && {command}'
            )
            logging.info(stdout.read().decode())

        logging.info('Creating test instances')
        for command in terraform_commands:
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/launch_test_instances/{arch}/ && {command}'
            )
            logging.info(stdout.read().decode())
        time.sleep(120)
        logging.info('Test instances are ready')
        logging.info('Starting testing')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        gc_test_log = f'genericcloud_test_{timestamp}.log'
        cmd = f'cd {self.cloud_images_path} && ' \
              f'py.test -v --hosts=almalinux-test-1,almalinux-test-2 ' \
              f'--ssh-config={test_path_tf}/launch_test_instances/{arch}/ssh-config ' \
              f'{test_path_tf}/launch_test_instances/{arch}/test_genericcloud.py 2>&1 | tee ./{gc_test_log}'
        try:
            stdout, _ = ssh.safe_execute(cmd)
            logging.info(stdout.read().decode())
        finally:
            self.upload_to_bucket(builder, ['genericcloud_test*.log'])
            logging.info(stdout.read().decode())

            sftp.get(
                f'{self.cloud_images_path}/{gc_test_log}',
                f'{self.arch}-{gc_test_log}')
            logging.info(stdout.read().decode())
            logging.info('Tested')
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/launch_test_instances/{arch}/ && '
                f'terraform destroy --auto-approve')
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/upload_image/{arch}/ && '
                f'terraform destroy --auto-approve')
        ssh.close()
        logging.info('Connection closed')


def generate_clouds(yaml_template) -> str:
    """
    Generates clouds.yaml
    """
    env = Environment(loader=DictLoader({'clouds': yaml_template}))
    template = env.get_template('clouds')
    return template.render(config=settings)


class AwsStage2(KVM):

    """
    AWS Stage 2 for building x86_64 AWS AMI.
    """

    def __init__(self, arch):
        super().__init__('aws-stage-2', arch)

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
            output = stdout.read().decode()
            logging.info(output)
            ami = None
            for line in output.splitlines():
                logging.info(line)
                if line.startswith('us-east-1'):
                    ami = line.split(':')[-1].strip()
                    logging.info(ami)
            with open(f'ami_id_{self.arch}.txt', 'w') as f:
                f.write(ami)
            logging.info('AWS AMI built')
        finally:
            pass
        cmd = f'bash -c "sha256sum /home/ec2-user/cloud-images/{aws2_build_log}"'
        stdout, _ = ssh.safe_execute(cmd)
        checksum = stdout.read().decode().split()[0]
        sftp = ssh.open_sftp()
        sftp.get(
            f'{self.sftp_path}{aws2_build_log}',
            f'{self.name}-{aws2_build_log}'
        )
        stdout = stdout.read().decode()
        logging.info(stdout)
        output = Popen(
            ['aws', 's3', 'cp', f'{self.name}-{aws2_build_log}',
             f's3://{settings.bucket}/{settings.build_number}-{settings.image.replace(" ", "_")}-{self.arch}-{timestamp}/',
             '--metadata', f'sha256={checksum}'], shell=True,
            stderr=STDOUT, stdout=PIPE
        )
        for line in output.stdout:
            logging.info(line.decode())
        ssh.close()
        logging.info('Connection closed')


class Equinix(BaseHypervisor):

    """
    Equnix Server for building and testing images.
    """

    def __init__(self, name='equinix', arch='aarch64'):
        """
        KVM initialization.
        """
        super().__init__(name, arch)

    @staticmethod
    def init_stage(builder: Builder):
        """
        builder: Builder
            Main Builder Configuration.

        Makes initialization of Equinix Server for the image building.
        """
        ssh = builder.ssh_equinix_connect()
        logging.info('Connection is good')
        stdout, _ = ssh.safe_execute(
            'git clone https://github.com/AlmaLinux/cloud-images.git')
        logging.info(stdout.read().decode())
        ssh.close()
        logging.info('Connection closed')

    def build_stage(self, builder: Builder):
        ssh = builder.ssh_equinix_connect()

        logging.info('Packer initialization')
        stdout, _ = ssh.safe_execute('packer.io init /root/cloud-images 2>&1')
        logging.info(stdout.read().decode())
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        gc_build_log = f'{settings.image.replace(" ", "_")}_{self.arch}_build_{timestamp}.log'
        logging.info(f'Building {settings.image}')
        try:
            stdout, _ = ssh.safe_execute(
                f'cd /root/cloud-images && '
                f'packer.io build -var qemu_binary="/usr/libexec/qemu-kvm" '
                f'-only=qemu.almalinux-8-gencloud-aarch64 . '
                f'2>&1 | tee ./{gc_build_log}'
            )
        finally:
            files = [f'{settings.image.replace(" ", "_")}_{self.arch}_build*.log',
                     'output-almalinux-8-gencloud-aarch64/*.qcow2']
            for file in files:
                cmd = f'bash -c "sha256sum /root/cloud-images/{file}"'
                stdout, _ = ssh.safe_execute(cmd)
                checksum = stdout.read().decode().split()[0]
                cmd = f'bash -c "aws s3 cp /root/cloud-images/{file} ' \
                      f's3://{settings.bucket}/{settings.build_number}-{settings.image.replace(" ", "_")}-{self.arch}-{timestamp}/' \
                      f' --metadata sha256={checksum}"'
                stdout, _ = ssh.safe_execute(cmd)
                logging.info(stdout.read().decode())
                logging.info('Uploaded')
        sftp = ssh.open_sftp()
        sftp.get(
            f'/root/cloud-images/{gc_build_log}',
            f'{self.name}-{gc_build_log}')
        logging.info(stdout.read().decode())
        logging.info(f'{settings.image} built')
        ssh.close()
        logging.info('Connection closed')

    def test_openstack(self, builder: Builder):
        """
        builder: Builder
            Main Builder Configuration.

        Run Testinfra tests for the built openstack image.
        """
        yaml = os.path.join(os.getcwd(), 'clouds.yaml.j2')
        content = open(yaml, 'r').read()
        yaml_content = generate_clouds(content)

        ssh = builder.ssh_equinix_connect()
        sftp = ssh.open_sftp()

        sftp.put(str(builder.AWS_KEY_PATH.absolute()), '/root/.ssh/alcib_rsa4096')

        cmd = 'sudo chmod 700 /root/.ssh && sudo chmod 600 /root/.ssh/alcib_rsa4096'
        stdout, _ = ssh.safe_execute(cmd)

        stdout, _ = ssh.safe_execute('mkdir -p /root/.config/openstack/')
        yaml_file = sftp.file('/root/.config/openstack/clouds.yaml', "w")
        yaml_file.write(yaml_content)
        yaml_file.flush()

        arch = self.arch if self.arch == 'aarch64' else 'amd64'
        test_path_tf = '/root/cloud-images/tests/genericcloud'
        logging.info('Uploading openstack image')

        stdout, _ = ssh.safe_execute(
            f'cp '
            f'/root/cloud-images/output-almalinux-8-gencloud-aarch64/*.qcow2 '
            f'{test_path_tf}/upload_image/{arch}/')
        terraform_commands = ['terraform init', 'terraform fmt',
                              'terraform validate',
                              'terraform apply --auto-approve']
        for command in terraform_commands:
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/upload_image/{arch}/ && {command}'
            )
            logging.info(stdout.read().decode())

        logging.info('Creating test instances')
        for command in terraform_commands:
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/launch_test_instances/{arch}/ && {command}'
            )
            logging.info(stdout.read().decode())
        time.sleep(120)
        logging.info('Test instances are ready')
        logging.info('Starting testing')
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        gc_test_log = f'genericcloud_test_{timestamp}.log'
        cmd = f'cd /root/cloud-images && ' \
              f'py.test -v --hosts=almalinux-test-1,almalinux-test-2 ' \
              f'--ssh-config={test_path_tf}/launch_test_instances/{arch}/ssh-config ' \
              f'{test_path_tf}/launch_test_instances/{arch}/test_genericcloud.py 2>&1 | tee ./{gc_test_log}'
        try:
            stdout, _ = ssh.safe_execute(cmd)
            logging.info(stdout.read().decode())
        finally:
            cmd = f'bash -c "sha256sum /root/cloud-images/{gc_test_log}"'
            stdout, _ = ssh.safe_execute(cmd)
            checksum = stdout.read().decode().split()[0]
            cmd = f'bash -c "aws s3 cp /root/cloud-images/{gc_test_log} ' \
                  f's3://{settings.bucket}/{settings.build_number}-{settings.image.replace(" ", "_")}-{self.arch}-{timestamp}/' \
                  f' --metadata sha256={checksum}"'
            stdout, _ = ssh.safe_execute(cmd)
            logging.info(stdout.read().decode())
            logging.info('Uploaded')

            sftp.get(
                f'/root/cloud-images/{gc_test_log}',
                f'{self.arch}-{gc_test_log}')
            logging.info(stdout.read().decode())
            logging.info('Tested')
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/launch_test_instances/{arch}/ && '
                f'terraform destroy --auto-approve')
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/upload_image/{arch}/ && '
                f'terraform destroy --auto-approve')
        ssh.close()
        logging.info('Connection closed')

    def release_and_sign_stage(self, builder: Builder):
        timestamp = str(datetime.date(datetime.today())).replace('-', '')
        qcow_name = f'AlmaLinux-8-GenericCloud-8.5-{timestamp}.aarch64.qcow2'
        ftp_path = '/var/ftp/pub/cloudlinux/almalinux/8/cloud/aarch64'
        ssh_equinix = builder.ssh_equinix_connect()
        stdout, _ = ssh_equinix.safe_execute(
            f'scp /root/cloud-images/*.qcow2 '
            f'mockbuild@192.168.246.161:{ftp_path}/images/{qcow_name}'
        )
        logging.info(stdout.read().decode())
        koji_release(ftp_path, qcow_name, builder)
        ssh_equinix.close()

    @staticmethod
    def teardown_equinix_stage(builder: Builder):
        """
        builder: Builder
            Main Builder Configuration.

        Cleans up Equinix Server.
        """
        ssh = builder.ssh_equinix_connect()
        cmd = 'sudo rm -r /root/cloud-images/ && sudo rm /root/.ssh/alcib_rsa4096'
        stdout, _ = ssh.safe_execute(cmd)
        logging.info(stdout.read().decode())
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
        'aws-stage-2': AwsStage2,
        'equinix': Equinix
    }[hypervisor_name](arch=arch)
