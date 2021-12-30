# How to release Amazon Machine Image on the AWS Marketplace

Enter the AWS Marketplace Management Portal with the root account from here: https://aws.amazon.com/marketplace/management

### Verify AMI before submitting
> To help verify your AMI before submitting it as a new product or version, you can use self-service
scanning.

#### Requirements

- IAM Role for AWS Marketplace access
- Product ID

##### IAM Role for AWS Marketplace access


The IAM Role can be create with this [guide](https://docs.aws.amazon.com/marketplace/latest/userguide/ami-single-ami-products.html?icmpid=docs_marketplace_helppane#single-ami-marketplace-ami-access)

You can get ARN of the existing IAM Role in two ways:

* Click on the [`Requests`](https://aws.amazon.com/marketplace/management/requests) select a latest request and click on `View details`. Look up for `"AccessRoleArn"` key in JSON formatted file.

* Find and a IAM Role with `AWSMarketplaceAmiIngestion` policy on [`AWS Management Console`](https://console.aws.amazon.com/console/home) > [`IAM > Roles`](https://console.aws.amazon.com/iamv2/home?#/roles)


##### Product ID

You can get Product id for each architeture by entering [`Server products`](https://aws.amazon.com/marketplace/management/products/server) and click on `AlmaLinux OS 8 (x86_64)` or `AlmaLinux OS 8 (arm64)`

##### Submit an AMI

Go to [`Assets` > `Amazon Machine Image`](https://aws.amazon.com/marketplace/management/manage-products)

Click on `Add AMI` button, enter an AMI ID you want to sumbit, and clik on `Next`.

Specify AMI details:

* IAM Access role ARN: `arn:aws:iam::123456891011:role/RoleName`
* OS username for Linux: `ec2-user`
* Scanning port for Linux: `22`

Review the information if it's correct and click on `Submit`

### Check scan status of the AMI submit request

Check `Scan status` on [`Assets` > `Amazon Machine Image`](https://aws.amazon.com/marketplace/management/manage-products)

> You receive scanning results quickly (typically, in less than an hour) with
clear feedback in a single location.


### Publish the AMI on the AWS Marketplace

You need to create a new version request.

1. Select `AlmaLinux OS 8 (x86_64)` or `AlmaLinux OS 8 (arm64)` on [`Products` > `Server`](https://aws.amazon.com/marketplace/management/products/server)
2. Click on `Request changes` > `Add new version`

* Version title: `8.5.20211116`
* Release notes: `AlmaLinux OS 8.5 is Now Available`
* Amazon machine image ID: `ami-0b4dad3b4322e5151`
* IAM access role ARN: `arn:aws:iam::123456891011:role/RoleName`
* Operating system user name: `ec2-user`
* Scanning port: `22`
* Usage instructions: `SSH to the instance and log in as 'ec2-user' using the key specified at launch.`
* Operating system (OS): `OTHERLINUX`
* OS version: `8.5`
* Recommended instance type: `t3.micro`
* Security group recommendations: `arn:aws:iam::123456891011:role/RoleName`
  - Protocol: `tcp`
  - Range start port: `22`
  - Range end port: `22`
  - Comma separated list of CIDR IPs: `0.0.0.0/0`

#### How to check status of the new version request

Go to the [`Request`](https://aws.amazon.com/marketplace/management/requests/) on the top of the page
