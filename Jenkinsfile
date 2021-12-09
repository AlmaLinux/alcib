def performCreateStages(String hypervisor) {
    return {
        sh "python3 -u main.py --stage init --hypervisor ${hypervisor}"
    }
}

def performBuildStages(String hypervisor) {
    return {
        sh "python3 -u main.py --stage build --hypervisor ${hypervisor}"
    }
}

def performTestStages(String hypervisor) {
    return {
        sh "python3 -u main.py --stage test --hypervisor ${hypervisor}"
    }
}

def performReleaseStages(String hypervisor) {
    return {
        sh "python3 -u main.py --stage release --hypervisor ${hypervisor}"
    }
}

def performDestroyStages(String hypervisor) {
    return {
        sh "python3 -u main.py --stage destroy --hypervisor ${hypervisor}"
    }
}

pipeline {
  agent any
  parameters {
      choice(name: 'IMAGE', choices: ['Vagrant Box', 'AWS AMI', 'Generic Cloud'], description: 'Cloud image to update: build, test, release', defaultValue: 'Vagrant')
      extendedChoice(defaultValue: 'x86_64', description: 'Architecture to build', descriptionPropertyValue: '', multiSelectDelimiter: ',', name: 'ARCH', quoteValue: false, saveJSONParameterToFile: false, type: 'PT_MULTI_SELECT', value: 'x86_64, aarch64', visibleItemCount: 2)
      extendedChoice(defaultValue: 'VirtualBox', description: 'Hypervisors options to  build Vagrant Box', descriptionPropertyValue: '', multiSelectDelimiter: ',', name: 'HYPERVISORS', quoteValue: false, saveJSONParameterToFile: false, type: 'PT_MULTI_SELECT', value: 'VirtualBox, VMWare_Desktop, KVM, HyperV', visibleItemCount: 4)
      string(name: 'BUCKET', defaultValue: 'alcib', description: 'S3 BUCKET NAME')
      string(name: 'VAGRANT', defaultValue: 'almalinux/8', description: 'Vagrant Cloud path to upload')
      booleanParam(defaultValue: true, description: 'Destroy AWS instance', name: 'DESTROY')
  }
  environment {
      AWS_ACCESS_KEY_ID = credentials('jenkins-aws-access-key-id')
      AWS_SECRET_ACCESS_KEY = credentials('jenkins-aws-secret-access-key')
      VAGRANT_CLOUD_ACCESS_KEY = credentials('jenkins-vagrant-user-access-key')
      SSH_KEY_FILE = credentials('jenkins-aclib-ssh-private-key')
      WINDOWS_CREDS = credentials('jenkins-windows-creds')
  }

  stages {
      stage('Create AWS instance') {
          when {
              expression { params.IMAGE == 'Vagrant Box' }
          }
          steps {
              script {
                  def jobs = [:]
                  for (hv in params.HYPERVISORS.replace('"', '').split(',')) {
                      jobs[hv] = performCreateStages(hv)
                  }
                  parallel jobs
              }
          }
      }
      stage('Create AWS instance') {
          when {
              expression { params.IMAGE == 'AWS AMI' }
          }
          steps {
              script {
                  sh "python3 -u main.py --stage init --hypervisor KVM"
              }
          }
      }
      stage('Build AWS AMI') {
          when {
              expression { params.IMAGE == 'AWS AMI' }
          }
          parallel {
              stage('Build AWS AMI aarch64') {
                  when {
                      expression { params.ARCH == 'aarch64' }
                  }
                  steps {
                      sh "python3 -u main.py --stage build --hypervisor KVM --arch ${arch}"
                  }
              }
              stage('Build AWS AMI x86_64') {
                   when {
                      expression { params.ARCH == 'x86_64' }
                  }
                  stages {
                      stage('Stage 1') {
                          sh "python3 -u main.py --stage build --hypervisor KVM --arch ${arch}"
                      }
                  }
              }
          }
      }
      stage('Build Vagrant Box') {
          when {
              expression { params.IMAGE == 'Vagrant Box' }
          }
          steps {
              script {
                  def jobs = [:]
                  for (hv in params.HYPERVISORS.replace('"', '').split(',')) {
                      jobs[hv] = performBuildStages(hv)
                  }
                  parallel jobs
              }
          }
      }
      stage('Test Vagrant Box') {
          when {
              expression { params.IMAGE == 'Vagrant Box' }
          }
          steps {
              script {
                  def jobs = [:]
                  for (hv in params.HYPERVISORS.replace('"', '').split(',')) {
                      jobs[hv] = performTestStages(hv)
                  }
                  parallel jobs
              }
          }
          post {
              success {
                  slackSend channel: '#test-auto-vagrant',
                            color: 'good',
                            message: "The build ${currentBuild.fullDisplayName} ready to be uploaded to Vagrant Cloud , please, approve: ${currentBuild.absoluteUrl}"
              }
          }
      }
      stage('Vagrant Cloud') {
          when {
              expression { params.IMAGE == 'Vagrant Box' }
          }
          steps {
              timeout(time:1, unit:'DAYS') {
                  script {
                      def userInput = input(
                        id: 'userInput',
                        message: 'Upload to Vagrant Cloud', ok: 'Starting uploading!',
                        parameters: [choice(name: 'RELEASE_SCOPE', choices: 'yes\nno'),
                                     string(name: 'VERSION', description: 'Release version', defaultValue: '8.5.20211111'),
                                     string(name: 'CHANGELOG', description: 'Vagrant box changelog', defaultValue: 'Test')]
                      )
                      env.RELEASE_SCOPE = userInput['RELEASE_SCOPE']
                      env.VERSION = userInput['VERSION']
                      env.CHANGELOG = userInput['CHANGELOG']
                      if (env.RELEASE_SCOPE == 'yes') {
                        def jobs = [:]
                        for (hv in params.HYPERVISORS.replace('"', '').split(',')) {
                            jobs[hv] = performReleaseStages(hv)
                        }
                        parallel jobs
                      }
                      if (env.RELEASE_SCOPE == 'yes') {
                        catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE') {
                            sh('curl --header \"Authorization: Bearer $VAGRANT_CLOUD_ACCESS_KEY\" https://app.vagrantup.com/api/v1/box/$VAGRANT/version/$VERSION/release --request PUT')
                        }
                      }
                  }
              }
          }
      }
      stage('Destroy AWS instance') {
          when {
              expression { params.DESTROY == true && params.IMAGE == 'Vagrant Box' }
          }
          steps {
              script {
                  def jobs = [:]
                  for (hv in params.HYPERVISORS.replace('"', '').split(',')) {
                      jobs[hv] = performDestroyStages(hv)
                  }
                  parallel jobs
              }
          }
      }
  }

  post {
      always {
          archiveArtifacts artifacts: '*.log'
      }
      success {
          when {
              expression { params.IMAGE == 'Vagrant Box' }
          }
          slackSend channel: '#test-auto-vagrant',
                    color: 'good',
                    message: "The build ${currentBuild.fullDisplayName} completed successfully : ${currentBuild.absoluteUrl}"
      }
      failure {
          when {
              expression { params.IMAGE == 'Vagrant Box' }
          }
          slackSend channel: '#test-auto-vagrant',
                    color: 'danger',
                    message: "The build ${currentBuild.fullDisplayName} failed : ${currentBuild.absoluteUrl}"
          script {
              if (params.DESTROY == true) {
                  def jobs = [:]
                  for (hv in params.HYPERVISORS.replace('"', '').split(',')) {
                      jobs[hv] = performDestroyStages(hv)
                  }
                  parallel jobs
              }
          }
      }
      aborted {
          when {
              expression { params.IMAGE == 'Vagrant Box' }
          }
          slackSend channel: '#test-auto-vagrant',
                    color: 'warning',
                    message: "The build ${currentBuild.fullDisplayName} was aborted : ${currentBuild.absoluteUrl}"
          script {
              if (params.DESTROY == true) {
                  def jobs = [:]
                  for (hv in params.HYPERVISORS.replace('"', '').split(',')) {
                      jobs[hv] = performDestroyStages(hv)
                  }
                  parallel jobs
              }
          }
      }
  }
}
