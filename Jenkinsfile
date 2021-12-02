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
      extendedChoice(defaultValue: 'VirtualBox', description: 'Hypervisors options to  build Vagrant Box', descriptionPropertyValue: '', multiSelectDelimiter: ',', name: 'HYPERVISORS', quoteValue: false, saveJSONParameterToFile: false, type: 'PT_MULTI_SELECT', value: 'VirtualBox, VMWare_Desktop, KVM, HyperV', visibleItemCount: 3)
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
      stage('Build Vagrant Box') {
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
              expression { params.DESTROY == true }
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
          slackSend channel: '#test-auto-vagrant',
                    color: 'good',
                    message: "The build ${currentBuild.fullDisplayName} completed successfully : ${currentBuild.absoluteUrl}"
      }
      failure {
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
