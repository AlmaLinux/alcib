# -*- mode:python; coding:utf-8; -*-
# author: Mariia Boldyreva <mboldyreva@cloudlinux.com>
# created: 2021-10-28

"""
Script settings validation.
"""

from pydantic import BaseSettings

__all__ = ['Settings']


class Settings(BaseSettings):

    """
    Settings for building Vagrant Boxes.
    """

    vagrant: str = ''
    bucket: str
    ssh_key_file: str
    vagrant_cloud_access_key: str = ''
    build_number: str
    image: str
    aarch_username: str = ''
    amd_username: str = ''
    aarch_password: str = ''
    amd_password: str = ''
    aarch_project_id: str = ''
    amd_project_id: str = ''


settings = Settings()
