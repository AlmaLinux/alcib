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


TIMESTAMP = str(datetime.date(datetime.today())).replace('-', '')
IMAGE = settings.image.replace(" ", "_")


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


def koji_release(ftp_path, qcow_name, builder):
    ssh_koji = builder.ssh_koji_connect()
    stdout, _ = ssh_koji.safe_execute(
        f'ln -sf {ftp_path}/images/{qcow_name} '
        f'{ftp_path}/AlmaLinux-8-GenericCloud-latest.x86_64.qcow2'
    )
    logging.info(stdout.read().decode())
    stdout, _ = ssh_koji.safe_execute('sha256sum *.qcow2 > CHECKSUM')
    logging.info(stdout.read().decode())
    deploy_path = 'deploy-repo-alma@192.168.246.161:/repo/almalinux/8/cloud/'
    stdout, _ = ssh_koji.safe_execute(
        f'rsync --dry-run -avSHP {ftp_path} {deploy_path}'
    )
    logging.info(stdout.read().decode())
    stdout, _ = ssh_koji.safe_execute(f'rsync -avSHP {ftp_path} {deploy_path}')
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
    logging.info('Executing %s', cmd)
    proc = Popen(cmd.split(), cwd=cwd_path, stderr=STDOUT, stdout=PIPE)
    for line in proc.stdout:
        logging.info(line.decode())
    proc.wait()
    if proc.returncode != 0:
        raise Exception('Command {0} execution failed {1}'.format(
            cmd, proc.returncode
        ))


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

    def download_qcow(self):
        # {self.build_number} - {IMAGE} - {self.name} - {self.arch} - {TIMESTAMP}
        s3_bucket = boto3.client(
            service_name='s3', region_name='us-east-1',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        logging.info(os.getenv('AWS_ACCESS_KEY_ID'))
        logging.info(os.getenv('AWS_SECRET_ACCESS_KEY'))
        # bucket_path = f'{self.build_number}-{IMAGE}-{self.name}-{self.arch}-{TIMESTAMP}'
        bucket_path = '19-Generic_Cloud-kvm-x86_64-20220208'
        work_dir = os.path.join(os.getcwd(), f'alcib/{bucket_path}')
        os.mkdir(work_dir, mode=0o777)
        os.mkdir(os.path.join(os.getcwd(), f'{bucket_path}'), mode=0o777)
        logging.info(work_dir)
        # qcow_name = f'almaLinux-8-GenericCloud-8.5.{self.arch}.qcow2'
        # qcow_tm_name = f'AlmaLinux-8-GenericCloud-8.5-{TIMESTAMP}.{self.arch}.qcow2'
        qcow_name = f'almaLinux-8-GenericCloud-8.5.x86_64.qcow2'
        qcow_tm_name = f'AlmaLinux-8-GenericCloud-8.5-{TIMESTAMP}.x86_64.qcow2'
        logging.info(qcow_tm_name)
        logging.info(bucket_path)
        logging.info(settings.bucket)
        # s3.download_file('your_bucket', 'k.png', '/Users/username/Desktop/k.png')
        key = f'{bucket_path}/{qcow_name}'
        logging.info(key)
        to = f'{bucket_path}/{qcow_tm_name}'
        logging.info(to)
        logging.info(os.getcwd())
        s3 = boto3.resource('s3', region_name='us-east-1',
                            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
                            )
        for i in range(5):
            try:
                s3_bucket.download_file(settings.bucket, key, to)
            except Exception as e:
                logging.exception(e)
                logging.info("Full path: %s", f'{bucket_path}/{qcow_name}')
                logging.info("Bucket objects: %s", [o['Key'] for o in s3_bucket.list_objects(Bucket='alcib-dev')['Contents']])
                time.sleep(60)
                if i == 4:
                    raise
        # if hypervisor == 'KVM':
        #     ssh = builder.ssh_aws_connect(instance_ip, name)
        # else:
        #     ssh = builder.ssh_equinix_connect()
        # sftp = ssh.open_sftp()
        # sftp.put(
        #     f'{path}/{qcow_name}', f'{qcow_tm_name}'
        # )
        return f'{work_dir}/{qcow_tm_name}'

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
        timestamp_name = f'{self.build_number}-{IMAGE}-{self.name}-{self.arch}-{TIMESTAMP}'
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
        logging.info('Building %s', settings.image)
        vb_build_log = f'{IMAGE}_{self.arch}_build_{TIMESTAMP}.log'
        if settings.image == 'Generic Cloud':
            cmd = self.packer_build_gencloud.format(vb_build_log)
        else:
            cmd = self.packer_build_cmd.format(vb_build_log)
        try:
            stdout, _ = ssh.safe_execute(cmd)
            logging.info(stdout.read().decode())
            sftp = ssh.open_sftp()
            sftp.get(f'{self.sftp_path}{vb_build_log}',
                     f'{self.name}-{vb_build_log}')
            logging.info('%s built', settings.image)
        finally:
            if settings.image == 'Generic Cloud':
                file = 'output-almalinux-8-gencloud-x86_64/*.qcow2'
            else:
                file = '*.box'
            self.upload_to_bucket(
                builder, [f'{IMAGE}_{self.arch}_build*.log', file]
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
        box = f'https://app.vagrantup.com/api/v1/box/{settings.vagrant}'
        version = os.environ.get('VERSION')
        stdout, _ = ssh.safe_execute(
            f'bash -c "sha256sum {self.cloud_images_path}/*.box"'
        )
        checksum = stdout.read().decode().split()[0]
        data = {'version': {'version': version,
                            'description': os.environ.get('CHANGELOG')}
                }
        get_headers = {
            'Authorization': f'Bearer {settings.vagrant_cloud_access_key}'
        }
        post_headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {settings.vagrant_cloud_access_key}'
        }
        response = requests.get(
            f'{box}/version/{version}', headers=get_headers
        )
        if response.status_code == 404:
            response = requests.post(
                f'{box}/versions', headers=post_headers, data=json.dumps(data)
            )
            logging.info(response.content.decode())
        unchanged = ['virtualbox', 'vmware_desktop', 'hyperv']
        hypervisor = self.name if self.name in unchanged else 'libvirt'
        logging.info('Preparing for uploading')
        data = {
            'provider': {
                'name': hypervisor,
                'checksum_type': 'sha256',
                'checksum': checksum
            }
        }
        response = requests.post(
            f'{box}/version/{version}/providers',
            headers=post_headers, data=json.dumps(data)
        )
        logging.info(response.content.decode())

        response = requests.get(
            f'{box}/version/{version}/provider/{hypervisor}/upload',
            headers=get_headers
        )
        logging.info(response.content.decode())
        upload_path = json.loads(response.content.decode()).get('upload_path')
        logging.info('Uploading the box')
        stdout, _ = ssh.safe_execute(
            f'bash -c "curl {upload_path} --request PUT '
            f'--upload-file {self.cloud_images_path}/*.box"'
        )
        logging.info(stdout.read().decode())
        ssh.close()
        logging.info('Connection closed')

    def prepare_openstack(
            self, ssh, cloud_path: str, arch: str, test_path_tf: str
    ) -> str:
        """
        Prepares Openstack images for futher testing.
        """
        logging.info('Uploading openstack image')
        stdout, _ = ssh.safe_execute(
            f'cp '
            f'{cloud_path}/cloud-images/output-almalinux-8-gencloud-{self.arch}/*.qcow2 '
            f'{test_path_tf}/upload_image/{arch}/'
        )
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
        return f'genericcloud_test_{TIMESTAMP}.log'


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
                        "ansible_ssh_private_key_file":
                            str(builder.AWS_KEY_PATH.absolute())
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
        stdout, _ = ssh.safe_execute(
            f'cd {self.cloud_images_path}/ && '
            f'cp {self.cloud_images_path}/tests/vagrant/Vagrantfile . '
            f'&& vagrant box add --name almalinux-8-test *.box && vagrant up'
        )
        logging.info(stdout.read().decode())
        logging.info('Prepared for test')
        stdout, _ = ssh.safe_execute(
            f'cd {self.cloud_images_path}/ && '
            f'vagrant ssh-config > .vagrant/ssh-config'
        )
        logging.info(stdout.read().decode())
        logging.info('Starting testing')
        vb_test_log = f'vagrant_box_test_{TIMESTAMP}.log'
        try:
            stdout, _ = ssh.safe_execute(
                f'cd {self.cloud_images_path}/ '
                f'&& py.test -v --hosts=almalinux-test-1,almalinux-test-2 '
                f'--ssh-config=.vagrant/ssh-config '
                f'{self.cloud_images_path}/tests/vagrant/test_vagrant.py '
                f'2>&1 | tee ./{vb_test_log}')
            logging.info(stdout.read().decode())
            sftp = ssh.open_sftp()
            sftp.get(f'{self.cloud_images_path}/{vb_test_log}',
                     f'{self.name}-{vb_test_log}')
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
        stdout, _ = ssh.safe_execute(
            'git clone https://github.com/AlmaLinux/cloud-images.git'
        )
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
        stdout, _ = ssh.safe_execute(
            f'cd {self.sftp_path} ; '
            f'vagrant ssh-config | Out-File -Encoding ascii -FilePath .vagrant/ssh-config'
        )
        logging.info(stdout.read().decode())
        logging.info('Starting testing')
        vb_test_log = f'vagrant_box_test_{TIMESTAMP}.log'
        cmd = f'cd {self.sftp_path} ; ' \
              f'py.test -v --hosts=almalinux-test-1,almalinux-test-2 ' \
              f'--ssh-config=.vagrant/ssh-config ' \
              f'{self.sftp_path}tests\\vagrant\\test_vagrant.py ' \
              f'| Out-File -FilePath {self.sftp_path}{vb_test_log}'
        try:
            stdout, _ = ssh.safe_execute(cmd)
            logging.info(stdout.read().decode())
            sftp = ssh.open_sftp()
            sftp.get(f'{self.sftp_path}{vb_test_log}',
                     f'{self.name}-{vb_test_log}')
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
        """
        Prepare AMI files for publishing.
        """
        with open(f'ami_id_{self.arch}.txt', 'r') as ami_file:
            ami_id = ami_file.read()
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Preparing csv and md')
        cmd = "cd {}/ && " \
              "export AWS_DEFAULT_REGION='us-east-1' && " \
              "export AWS_ACCESS_KEY_ID='{}' " \
              "&& export AWS_SECRET_ACCESS_KEY='{}' " \
              "&& {}/bin/aws_ami_mirror.py " \
              "-a {} --csv-output aws_amis-{}.csv " \
              "--md-output AWS_AMIS-{}.md --verbose".format(
                  self.cloud_images_path,
                  os.getenv('AWS_ACCESS_KEY_ID'),
                  os.getenv('AWS_SECRET_ACCESS_KEY'),
                  self.cloud_images_path,
                  ami_id, self.arch, self.arch)
        stdout, _ = ssh.safe_execute(cmd)
        logging.info(stdout.read().decode())
        self.upload_to_bucket(builder, ['aws_amis*.csv', 'AWS_AMIS*.md'])
        sftp = ssh.open_sftp()
        sftp.get(f'{self.sftp_path}/aws_amis-{self.arch}.csv',
                 f'aws_amis-{self.arch}.csv')
        sftp.get(f'{self.sftp_path}/AWS_AMIS-{self.arch}.md',
                 f'AWS_AMIS-{self.arch}.md')
        ssh.close()

    def release_and_sign_stage(self, builder: Builder):
        qcow_name = f'AlmaLinux-8-GenericCloud-8.5-{TIMESTAMP}.x86_64.qcow2'
        ftp_path = '/var/ftp/pub/cloudlinux/almalinux/8/cloud/x86_64'
        qcow_path = self.download_qcow()
        ssh_aws = builder.ssh_aws_connect(self.instance_ip, self.name)
        sftp = ssh_aws.open_sftp()
        sftp.put(qcow_path,
                 f'mockbuild@192.168.246.161:{ftp_path}/images/{qcow_name}')
        koji_release(ftp_path, qcow_name, builder)
        ssh_aws.close()

    def build_aws_stage(self, builder: Builder, arch: str):
        ssh = builder.ssh_aws_connect(self.instance_ip, self.name)
        logging.info('Packer initialization')
        stdout, _ = ssh.safe_execute('packer init ./cloud-images 2>&1')
        logging.info(stdout.read().decode())
        logging.info('Building AWS AMI')
        aws_build_log = f'aws_ami_build_{self.arch}_{TIMESTAMP}.log'
        if arch == 'x86_64':
            logging.info('Building Stage 1')
            cmd = "cd cloud-images && " \
                  "export AWS_DEFAULT_REGION='us-east-1' && " \
                  "export AWS_ACCESS_KEY_ID='{}' && " \
                  "export AWS_SECRET_ACCESS_KEY='{}' " \
                  "&& packer build -var aws_s3_bucket_name='{}' " \
                  "-var qemu_binary='/usr/libexec/qemu-kvm' " \
                  "-var aws_role_name='alma-images-prod-role' " \
                  "-only=qemu.almalinux-8-aws-stage1 . 2>&1 | tee ./{}".format(
                      os.getenv('AWS_ACCESS_KEY_ID'),
                      os.getenv('AWS_SECRET_ACCESS_KEY'),
                      settings.bucket, aws_build_log)
        else:
            cmd = "cd cloud-images && " \
                  "export AWS_DEFAULT_REGION='us-east-1' && " \
                  "export AWS_ACCESS_KEY_ID='{}' && " \
                  "export AWS_SECRET_ACCESS_KEY='{}' " \
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
        ami = save_ami_id(stdout, self.arch)
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
                aws_hypervisor.terraform_dir,
                'build-tools-on-ec2-userdata.yml'
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
        stdout, _ = ssh.safe_execute(
            'sudo chmod 700 /home/ec2-user/.ssh && '
            'sudo chmod 600 /home/ec2-user/.ssh/alcib_rsa4096'
        )
        arch = self.arch if self.arch == 'aarch64' else 'amd64'
        test_path_tf = f'{self.cloud_images_path}/tests/ami/launch_test_instances/{arch}'
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
        stdout, _ = ssh.safe_execute(
            f'cd {test_path_tf} && {cmd_export} && terraform output --json'
        )
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
        aws_test_log = f'aws_ami_test_{TIMESTAMP}.log'
        try:
            stdout, _ = ssh.safe_execute(
                f'cd {self.cloud_images_path} && '
                f'py.test -v --hosts=almalinux-test-1,almalinux-test-2 '
                f'--ssh-config={test_path_tf}/ssh-config '
                f'{self.cloud_images_path}/tests/ami/test_ami.py '
                f'2>&1 | tee ./{aws_test_log}'
            )
            logging.info(stdout.read().decode())
        finally:
            self.upload_to_bucket(builder, ['aws_ami_test*.log'])
        sftp.get(f'{self.cloud_images_path}/{aws_test_log}',
                 f'{self.arch}-{aws_test_log}')
        logging.info('Tested')
        stdout, _ = ssh.safe_execute(
            f'cd {test_path_tf} && {cmd_export} && '
            f'terraform destroy --auto-approve'
        )
        logging.info(stdout.read().decode())
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
        sftp.put(str(builder.AWS_KEY_PATH.absolute()),
                 '/home/ec2-user/.ssh/alcib_rsa4096')
        stdout, _ = ssh.safe_execute(
            'sudo chmod 700 /home/ec2-user/.ssh && '
            'sudo chmod 600 /home/ec2-user/.ssh/alcib_rsa4096'
        )
        yaml_file = sftp.file('/home/ec2-user/.config/openstack/clouds.yaml', "w")
        yaml_file.write(yaml_content)
        yaml_file.flush()
        arch = self.arch if self.arch == 'aarch64' else 'amd64'
        test_path_tf = f'{self.cloud_images_path}/tests/genericcloud'
        gc_test_log = self.prepare_openstack(
            ssh, '/home/ec2-user', arch, test_path_tf
        )
        script = f'{test_path_tf}/launch_test_instances/{arch}/test_genericcloud.py'
        cmd = f'cd {self.cloud_images_path} && ' \
              f'py.test -v --hosts=almalinux-test-1,almalinux-test-2 ' \
              f'--ssh-config={test_path_tf}/launch_test_instances/{arch}/ssh-config ' \
              f'{script} 2>&1 | tee ./{gc_test_log}'
        try:
            stdout, _ = ssh.safe_execute(cmd)
            logging.info(stdout.read().decode())
        finally:
            self.upload_to_bucket(builder, ['genericcloud_test*.log'])
            sftp.get(f'{self.cloud_images_path}/{gc_test_log}',
                     f'{self.arch}-{gc_test_log}')
            logging.info('Tested')
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/launch_test_instances/{arch}/ && '
                f'terraform destroy --auto-approve'
            )
            logging.info(stdout.read().decode())
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/upload_image/{arch}/ && '
                f'terraform destroy --auto-approve'
            )
            logging.info(stdout.read().decode())
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
        stdout, _ = ssh.safe_execute(
            f'cd {self.cloud_images_path} && sudo packer.io init .'
        )
        logging.info(stdout.read().decode())
        logging.info('Building AWS AMI')
        aws2_build_log = f'aws_ami_stage2_build_{TIMESTAMP}.log'
        try:
            stdout, _ = ssh.safe_execute(
                'cd cloud-images && sudo AWS_ACCESS_KEY_ID="{}" '
                'AWS_SECRET_ACCESS_KEY="{}" AWS_DEFAULT_REGION="us-east-1" '
                'packer.io build -only=amazon-chroot.almalinux-8-aws-stage2 '
                '. 2>&1 | tee ./{}'.format(
                    os.getenv('AWS_ACCESS_KEY_ID'),
                    os.getenv('AWS_SECRET_ACCESS_KEY'),
                    aws2_build_log
                )
            )
            output = stdout.read().decode()
            logging.info(output)
            save_ami_id(output, self.arch)
        finally:
            pass
        cmd = f'bash -c "sha256sum {self.cloud_images_path}/{aws2_build_log}"'
        stdout, _ = ssh.safe_execute(cmd)
        sftp = ssh.open_sftp()
        sftp.get(
            f'{self.sftp_path}{aws2_build_log}',
            f'{self.name}-{aws2_build_log}'
        )
        logging.info(stdout.read().decode())
        # doesn't actually uploads due to uninstalled aws cli, requieres another option
        # output = Popen(
        #     ['aws', 's3', 'cp', f'{self.name}-{aws2_build_log}',
        #      f's3://{settings.bucket}/{settings.build_number}-{IMAGE}-{self.arch}-{TIMESTAMP}/',
        #      '--metadata', f'sha256={stdout.read().decode().split()[0]}'],
        #     shell=True, stderr=STDOUT, stdout=PIPE
        # )
        # for line in output.stdout:
        #     logging.info(line.decode())
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
        Makes initialization of Equinix Server for the image building.

        builder: Builder
            Main Builder Configuration.
        """
        ssh = builder.ssh_equinix_connect()
        logging.info('Connection is good')
        stdout, _ = ssh.safe_execute(
            'git clone https://github.com/AlmaLinux/cloud-images.git'
        )
        logging.info(stdout.read().decode())
        ssh.close()
        logging.info('Connection closed')

    def upload_to_s3(self, ssh, file: str):
        """
        Uploads to S3 bucket without builder.
        """
        cmd = f'bash -c "sha256sum /root/cloud-images/{file}"'
        stdout, _ = ssh.safe_execute(cmd)
        stdout, _ = ssh.safe_execute(
            f'bash -c "aws s3 cp /root/cloud-images/{file} '
            f's3://{settings.bucket}/{settings.build_number}-{IMAGE}-{self.arch}-{TIMESTAMP}/ '
            f'--metadata sha256={stdout.read().decode().split()[0]}"')
        logging.info(stdout.read().decode())
        logging.info('Uploaded')

    def build_stage(self, builder: Builder):
        ssh = builder.ssh_equinix_connect()
        logging.info('Packer initialization')
        stdout, _ = ssh.safe_execute('packer.io init /root/cloud-images 2>&1')
        logging.info(stdout.read().decode())
        gc_build_log = f'{IMAGE}_{self.arch}_build_{TIMESTAMP}.log'
        logging.info('Building %s', settings.image)
        try:
            stdout, _ = ssh.safe_execute(
                f'cd /root/cloud-images && '
                f'packer.io build -var qemu_binary="/usr/libexec/qemu-kvm" '
                f'-only=qemu.almalinux-8-gencloud-aarch64 . '
                f'2>&1 | tee ./{gc_build_log}'
            )
        finally:
            files = [
                f'{IMAGE}_{self.arch}_build*.log',
                'output-almalinux-8-gencloud-aarch64/*.qcow2'
            ]
            for file in files:
                self.upload_to_s3(ssh, file)
        sftp = ssh.open_sftp()
        sftp.get(f'/root/cloud-images/{gc_build_log}',
                 f'{self.name}-{gc_build_log}')
        logging.info(stdout.read().decode())
        logging.info('%s built', settings.image)
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
        sftp.put(str(builder.AWS_KEY_PATH.absolute()),
                 '/root/.ssh/alcib_rsa4096')
        stdout, _ = ssh.safe_execute('sudo chmod 700 /root/.ssh && '
                                     'sudo chmod 600 /root/.ssh/alcib_rsa4096')
        stdout, _ = ssh.safe_execute('mkdir -p /root/.config/openstack/')
        yaml_file = sftp.file('/root/.config/openstack/clouds.yaml', "w")
        yaml_file.write(yaml_content)
        yaml_file.flush()

        arch = self.arch if self.arch == 'aarch64' else 'amd64'
        test_path_tf = '/root/cloud-images/tests/genericcloud/'
        gc_test_log = self.prepare_openstack(
            ssh, '/root', arch, test_path_tf
        )
        script = f'{test_path_tf}/launch_test_instances/{arch}/test_genericcloud.py'
        try:
            stdout, _ = ssh.safe_execute(
                f'cd /root/cloud-images && '
                f'py.test -v --hosts=almalinux-test-1,almalinux-test-2 '
                f'--ssh-config={test_path_tf}/launch_test_instances/{arch}/ssh-config '
                f'{script} 2>&1 | tee ./{gc_test_log}')
            logging.info(stdout.read().decode())
        finally:
            self.upload_to_s3(ssh, gc_test_log)
            sftp.get(f'/root/cloud-images/{gc_test_log}',
                     f'{self.arch}-{gc_test_log}')
            logging.info('Tested')
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/launch_test_instances/{arch}/ && '
                f'terraform destroy --auto-approve'
            )
            stdout, _ = ssh.safe_execute(
                f'cd {test_path_tf}/upload_image/{arch}/ && '
                f'terraform destroy --auto-approve'
            )
        ssh.close()
        logging.info('Connection closed')

    def release_and_sign_stage(self, builder: Builder):
        qcow_name = f'AlmaLinux-8-GenericCloud-8.5-{TIMESTAMP}.aarch64.qcow2'
        ftp_path = '/var/ftp/pub/cloudlinux/almalinux/8/cloud/aarch64'
        qcow_path = self.download_qcow()
        ssh_equinix = builder.ssh_equinix_connect()
        sftp = ssh_equinix.open_sftp()
        sftp.put(qcow_path,
                 f'mockbuild@192.168.246.161:{ftp_path}/images/{qcow_name}')
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
