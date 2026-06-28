#!/usr/bin/env python3
"""
AWS ECS deployment script for VitalGraph Fuseki using boto3.
Creates ECS cluster, EFS storage, ALB, and deploys Fuseki container.
"""

import boto3
import json
import time
import argparse
from typing import Dict, List, Optional
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FusekiAWSDeployer:
    """Deploy VitalGraph Fuseki to AWS ECS with EFS storage."""
    
    def __init__(self, region: str = 'us-east-1'):
        """Initialize AWS clients."""
        self.region = region
        self.ec2 = boto3.client('ec2', region_name=region)
        self.ecs = boto3.client('ecs', region_name=region)
        self.efs = boto3.client('efs', region_name=region)
        self.elbv2 = boto3.client('elbv2', region_name=region)
        self.iam = boto3.client('iam', region_name=region)
        self.logs = boto3.client('logs', region_name=region)
        self.ecr = boto3.client('ecr', region_name=region)
        
        # Deployment configuration
        self.config = {
            'cluster_name': 'vitalgraph-cluster',
            'service_name': 'vitalgraph-fuseki-service',
            'task_family': 'vitalgraph-fuseki',
            'container_name': 'fuseki',
            'image_name': 'vitalgraph-fuseki',
            'log_group': '/ecs/vitalgraph-fuseki'
        }
    
    def get_account_id(self) -> str:
        """Get AWS account ID."""
        sts = boto3.client('sts')
        return sts.get_caller_identity()['Account']
    
    def create_ecr_repository(self) -> str:
        """Create ECR repository if it doesn't exist."""
        logger.info("Creating ECR repository...")
        
        try:
            response = self.ecr.describe_repositories(
                repositoryNames=[self.config['image_name']]
            )
            repo_uri = response['repositories'][0]['repositoryUri']
            logger.info(f"ECR repository already exists: {repo_uri}")
        except self.ecr.exceptions.RepositoryNotFoundException:
            response = self.ecr.create_repository(
                repositoryName=self.config['image_name'],
                imageScanningConfiguration={'scanOnPush': True},
                encryptionConfiguration={'encryptionType': 'AES256'}
            )
            repo_uri = response['repository']['repositoryUri']
            logger.info(f"Created ECR repository: {repo_uri}")
        
        return repo_uri
    
    def create_vpc_resources(self, vpc_id: str, subnet_ids: List[str]) -> Dict:
        """Create security groups and other VPC resources."""
        logger.info("Creating VPC resources...")
        
        # Create security group for EFS
        efs_sg = self.ec2.create_security_group(
            GroupName='vitalgraph-efs-sg',
            Description='Security group for VitalGraph EFS',
            VpcId=vpc_id
        )
        efs_sg_id = efs_sg['GroupId']
        
        # Create security group for ECS tasks
        ecs_sg = self.ec2.create_security_group(
            GroupName='vitalgraph-ecs-sg',
            Description='Security group for VitalGraph ECS tasks',
            VpcId=vpc_id
        )
        ecs_sg_id = ecs_sg['GroupId']
        
        # Create security group for ALB
        alb_sg = self.ec2.create_security_group(
            GroupName='vitalgraph-alb-sg',
            Description='Security group for VitalGraph ALB',
            VpcId=vpc_id
        )
        alb_sg_id = alb_sg['GroupId']
        
        # Configure security group rules
        # EFS: Allow NFS from ECS
        self.ec2.authorize_security_group_ingress(
            GroupId=efs_sg_id,
            IpPermissions=[{
                'IpProtocol': 'tcp',
                'FromPort': 2049,
                'ToPort': 2049,
                'UserIdGroupPairs': [{'GroupId': ecs_sg_id}]
            }]
        )
        
        # ECS: Allow port 3030 from ALB
        self.ec2.authorize_security_group_ingress(
            GroupId=ecs_sg_id,
            IpPermissions=[{
                'IpProtocol': 'tcp',
                'FromPort': 3030,
                'ToPort': 3030,
                'UserIdGroupPairs': [{'GroupId': alb_sg_id}]
            }]
        )
        
        # ALB: Allow HTTP from internet
        self.ec2.authorize_security_group_ingress(
            GroupId=alb_sg_id,
            IpPermissions=[{
                'IpProtocol': 'tcp',
                'FromPort': 80,
                'ToPort': 80,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            }]
        )
        
        logger.info(f"Created security groups: EFS={efs_sg_id}, ECS={ecs_sg_id}, ALB={alb_sg_id}")
        
        return {
            'efs_sg_id': efs_sg_id,
            'ecs_sg_id': ecs_sg_id,
            'alb_sg_id': alb_sg_id
        }
    
    def create_efs_filesystem(self, subnet_ids: List[str], efs_sg_id: str) -> Dict:
        """Create EFS filesystem with mount targets."""
        logger.info("Creating EFS filesystem...")
        
        # Create EFS filesystem
        efs_response = self.efs.create_file_system(
            CreationToken=f'vitalgraph-fuseki-{int(time.time())}',
            PerformanceMode='generalPurpose',
            ThroughputMode='provisioned',
            ProvisionedThroughputInMibps=100,
            Encrypted=True,
            Tags=[
                {'Key': 'Name', 'Value': 'vitalgraph-fuseki-storage'}
            ]
        )
        
        filesystem_id = efs_response['FileSystemId']
        logger.info(f"Created EFS filesystem: {filesystem_id}")
        
        # Wait for filesystem to be available
        logger.info("Waiting for EFS filesystem to be available...")
        while True:
            response = self.efs.describe_file_systems(FileSystemId=filesystem_id)
            state = response['FileSystems'][0]['LifeCycleState']
            if state == 'available':
                break
            time.sleep(5)
        
        # Create mount targets
        mount_target_ids = []
        for subnet_id in subnet_ids:
            try:
                mt_response = self.efs.create_mount_target(
                    FileSystemId=filesystem_id,
                    SubnetId=subnet_id,
                    SecurityGroups=[efs_sg_id]
                )
                mount_target_ids.append(mt_response['MountTargetId'])
                logger.info(f"Created mount target in subnet {subnet_id}")
            except Exception as e:
                logger.warning(f"Failed to create mount target in {subnet_id}: {e}")
        
        # Create access point
        ap_response = self.efs.create_access_point(
            FileSystemId=filesystem_id,
            PosixUser={
                'Uid': 1000,
                'Gid': 1000
            },
            RootDirectory={
                'Path': '/vitalgraph',
                'CreationInfo': {
                    'OwnerUid': 1000,
                    'OwnerGid': 1000,
                    'Permissions': 755
                }
            },
            Tags=[
                {'Key': 'Name', 'Value': 'vitalgraph-fuseki-access-point'}
            ]
        )
        
        access_point_id = ap_response['AccessPointId']
        logger.info(f"Created EFS access point: {access_point_id}")
        
        return {
            'filesystem_id': filesystem_id,
            'access_point_id': access_point_id,
            'mount_target_ids': mount_target_ids
        }
    
    def create_iam_roles(self) -> Dict:
        """Create IAM roles for ECS tasks."""
        logger.info("Creating IAM roles...")
        
        # Task execution role
        execution_role_doc = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        try:
            exec_role_response = self.iam.create_role(
                RoleName='vitalgraph-fuseki-execution-role',
                AssumeRolePolicyDocument=json.dumps(execution_role_doc),
                Description='Execution role for VitalGraph Fuseki ECS tasks'
            )
            execution_role_arn = exec_role_response['Role']['Arn']
        except self.iam.exceptions.EntityAlreadyExistsException:
            execution_role_arn = self.iam.get_role(
                RoleName='vitalgraph-fuseki-execution-role'
            )['Role']['Arn']
        
        # Attach managed policy
        self.iam.attach_role_policy(
            RoleName='vitalgraph-fuseki-execution-role',
            PolicyArn='arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy'
        )
        
        # Task role
        task_role_doc = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        try:
            task_role_response = self.iam.create_role(
                RoleName='vitalgraph-fuseki-task-role',
                AssumeRolePolicyDocument=json.dumps(task_role_doc),
                Description='Task role for VitalGraph Fuseki ECS tasks'
            )
            task_role_arn = task_role_response['Role']['Arn']
        except self.iam.exceptions.EntityAlreadyExistsException:
            task_role_arn = self.iam.get_role(
                RoleName='vitalgraph-fuseki-task-role'
            )['Role']['Arn']
        
        # Create EFS access policy
        efs_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "elasticfilesystem:ClientMount",
                        "elasticfilesystem:ClientWrite",
                        "elasticfilesystem:ClientRootAccess"
                    ],
                    "Resource": "*"
                }
            ]
        }
        
        try:
            self.iam.create_policy(
                PolicyName='vitalgraph-fuseki-efs-policy',
                PolicyDocument=json.dumps(efs_policy),
                Description='EFS access policy for VitalGraph Fuseki'
            )
        except self.iam.exceptions.EntityAlreadyExistsException:
            pass
        
        # Attach EFS policy to task role
        account_id = self.get_account_id()
        efs_policy_arn = f'arn:aws:iam::{account_id}:policy/vitalgraph-fuseki-efs-policy'
        self.iam.attach_role_policy(
            RoleName='vitalgraph-fuseki-task-role',
            PolicyArn=efs_policy_arn
        )
        
        logger.info(f"Created IAM roles: execution={execution_role_arn}, task={task_role_arn}")
        
        return {
            'execution_role_arn': execution_role_arn,
            'task_role_arn': task_role_arn
        }
    
    def create_log_group(self):
        """Create CloudWatch log group."""
        logger.info("Creating CloudWatch log group...")
        
        try:
            self.logs.create_log_group(
                logGroupName=self.config['log_group'],
                retentionInDays=30
            )
            logger.info(f"Created log group: {self.config['log_group']}")
        except self.logs.exceptions.ResourceAlreadyExistsException:
            logger.info(f"Log group already exists: {self.config['log_group']}")
    
    def create_ecs_cluster(self):
        """Create ECS cluster."""
        logger.info("Creating ECS cluster...")
        
        try:
            response = self.ecs.create_cluster(
                clusterName=self.config['cluster_name'],
                capacityProviders=['FARGATE'],
                defaultCapacityProviderStrategy=[
                    {
                        'capacityProvider': 'FARGATE',
                        'weight': 1
                    }
                ]
            )
            logger.info(f"Created ECS cluster: {self.config['cluster_name']}")
        except Exception as e:
            if 'already exists' in str(e):
                logger.info(f"ECS cluster already exists: {self.config['cluster_name']}")
            else:
                raise
    
    def create_load_balancer(self, vpc_id: str, public_subnet_ids: List[str], alb_sg_id: str) -> Dict:
        """Create Application Load Balancer."""
        logger.info("Creating Application Load Balancer...")
        
        # Create ALB
        alb_response = self.elbv2.create_load_balancer(
            Name='vitalgraph-fuseki-alb',
            Subnets=public_subnet_ids,
            SecurityGroups=[alb_sg_id],
            Scheme='internet-facing',
            Type='application',
            IpAddressType='ipv4'
        )
        
        alb_arn = alb_response['LoadBalancers'][0]['LoadBalancerArn']
        alb_dns = alb_response['LoadBalancers'][0]['DNSName']
        
        # Create target group
        tg_response = self.elbv2.create_target_group(
            Name='vitalgraph-fuseki-tg',
            Protocol='HTTP',
            Port=3030,
            VpcId=vpc_id,
            TargetType='ip',
            HealthCheckPath='/$/ping',
            HealthCheckIntervalSeconds=30,
            HealthCheckTimeoutSeconds=10,
            HealthyThresholdCount=2,
            UnhealthyThresholdCount=3
        )
        
        target_group_arn = tg_response['TargetGroups'][0]['TargetGroupArn']
        
        # Create listener
        self.elbv2.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol='HTTP',
            Port=80,
            DefaultActions=[
                {
                    'Type': 'forward',
                    'TargetGroupArn': target_group_arn
                }
            ]
        )
        
        logger.info(f"Created ALB: {alb_dns}")
        
        return {
            'alb_arn': alb_arn,
            'alb_dns': alb_dns,
            'target_group_arn': target_group_arn
        }
    
    def create_task_definition(self, image_uri: str, efs_info: Dict, iam_roles: Dict) -> str:
        """Create ECS task definition."""
        logger.info("Creating ECS task definition...")
        
        task_def = {
            'family': self.config['task_family'],
            'networkMode': 'awsvpc',
            'requiresCompatibilities': ['FARGATE'],
            'cpu': '1024',
            'memory': '2048',
            'executionRoleArn': iam_roles['execution_role_arn'],
            'taskRoleArn': iam_roles['task_role_arn'],
            'containerDefinitions': [
                {
                    'name': self.config['container_name'],
                    'image': image_uri,
                    'essential': True,
                    'portMappings': [
                        {
                            'containerPort': 3030,
                            'protocol': 'tcp'
                        }
                    ],
                    'environment': [
                        {'name': 'MEMORY_LIMIT', 'value': '2048'},
                        {'name': 'EFS_MOUNT_POINT', 'value': '/efs'},
                        {'name': 'JAVA_OPTIONS', 'value': '-Xmx1536m -Xms1536m -XX:+UseG1GC'}
                    ],
                    'mountPoints': [
                        {
                            'sourceVolume': 'fuseki-efs',
                            'containerPath': '/efs',
                            'readOnly': False
                        }
                    ],
                    'logConfiguration': {
                        'logDriver': 'awslogs',
                        'options': {
                            'awslogs-group': self.config['log_group'],
                            'awslogs-region': self.region,
                            'awslogs-stream-prefix': 'ecs'
                        }
                    }
                }
            ],
            'volumes': [
                {
                    'name': 'fuseki-efs',
                    'efsVolumeConfiguration': {
                        'fileSystemId': efs_info['filesystem_id'],
                        'rootDirectory': '/',
                        'transitEncryption': 'ENABLED',
                        'authorizationConfig': {
                            'accessPointId': efs_info['access_point_id'],
                            'iam': 'ENABLED'
                        }
                    }
                }
            ]
        }
        
        response = self.ecs.register_task_definition(**task_def)
        task_def_arn = response['taskDefinition']['taskDefinitionArn']
        
        logger.info(f"Created task definition: {task_def_arn}")
        return task_def_arn
    
    def create_ecs_service(self, subnet_ids: List[str], ecs_sg_id: str, target_group_arn: str):
        """Create ECS service."""
        logger.info("Creating ECS service...")
        
        service_def = {
            'serviceName': self.config['service_name'],
            'cluster': self.config['cluster_name'],
            'taskDefinition': self.config['task_family'],
            'desiredCount': 1,
            'launchType': 'FARGATE',
            'networkConfiguration': {
                'awsvpcConfiguration': {
                    'subnets': subnet_ids,
                    'securityGroups': [ecs_sg_id],
                    'assignPublicIp': 'DISABLED'
                }
            },
            'loadBalancers': [
                {
                    'targetGroupArn': target_group_arn,
                    'containerName': self.config['container_name'],
                    'containerPort': 3030
                }
            ],
            'deploymentConfiguration': {
                'maximumPercent': 100,
                'minimumHealthyPercent': 0
            },
            'healthCheckGracePeriodSeconds': 120
        }
        
        try:
            response = self.ecs.create_service(**service_def)
            logger.info(f"Created ECS service: {self.config['service_name']}")
        except Exception as e:
            if 'already exists' in str(e):
                logger.info(f"ECS service already exists, updating: {self.config['service_name']}")
                self.ecs.update_service(
                    cluster=self.config['cluster_name'],
                    service=self.config['service_name'],
                    taskDefinition=self.config['task_family'],
                    forceNewDeployment=True
                )
            else:
                raise
    
    def deploy(self, vpc_id: str, private_subnet_ids: List[str], 
               public_subnet_ids: List[str], image_uri: Optional[str] = None):
        """Deploy complete VitalGraph Fuseki infrastructure."""
        logger.info("Starting VitalGraph Fuseki deployment...")
        
        # Create ECR repository if image_uri not provided
        if not image_uri:
            repo_uri = self.create_ecr_repository()
            account_id = self.get_account_id()
            image_uri = f"{account_id}.dkr.ecr.{self.region}.amazonaws.com/{self.config['image_name']}:latest"
            logger.info(f"Using image URI: {image_uri}")
        
        # Create resources
        vpc_resources = self.create_vpc_resources(vpc_id, private_subnet_ids)
        efs_info = self.create_efs_filesystem(private_subnet_ids, vpc_resources['efs_sg_id'])
        iam_roles = self.create_iam_roles()
        self.create_log_group()
        self.create_ecs_cluster()
        alb_info = self.create_load_balancer(vpc_id, public_subnet_ids, vpc_resources['alb_sg_id'])
        
        # Wait for EFS mount targets to be available
        logger.info("Waiting for EFS mount targets to be available...")
        time.sleep(30)
        
        task_def_arn = self.create_task_definition(image_uri, efs_info, iam_roles)
        self.create_ecs_service(private_subnet_ids, vpc_resources['ecs_sg_id'], alb_info['target_group_arn'])
        
        logger.info("Deployment completed successfully!")
        logger.info(f"Access Fuseki at: http://{alb_info['alb_dns']}")
        logger.info(f"Health check: http://{alb_info['alb_dns']}/$/ping")
        
        return {
            'alb_dns': alb_info['alb_dns'],
            'cluster_name': self.config['cluster_name'],
            'service_name': self.config['service_name'],
            'efs_filesystem_id': efs_info['filesystem_id']
        }


def main():
    """Main deployment function."""
    parser = argparse.ArgumentParser(description='Deploy VitalGraph Fuseki to AWS ECS')
    parser.add_argument('--region', default='us-east-1', help='AWS region')
    parser.add_argument('--vpc-id', required=True, help='VPC ID')
    parser.add_argument('--private-subnets', required=True, 
                       help='Comma-separated private subnet IDs')
    parser.add_argument('--public-subnets', required=True,
                       help='Comma-separated public subnet IDs')
    parser.add_argument('--image-uri', help='ECR image URI (optional)')
    
    args = parser.parse_args()
    
    private_subnets = args.private_subnets.split(',')
    public_subnets = args.public_subnets.split(',')
    
    deployer = FusekiAWSDeployer(region=args.region)
    
    try:
        result = deployer.deploy(
            vpc_id=args.vpc_id,
            private_subnet_ids=private_subnets,
            public_subnet_ids=public_subnets,
            image_uri=args.image_uri
        )
        
        print("\n🎉 Deployment Summary:")
        print(f"ALB DNS: {result['alb_dns']}")
        print(f"Cluster: {result['cluster_name']}")
        print(f"Service: {result['service_name']}")
        print(f"EFS: {result['efs_filesystem_id']}")
        
    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        raise


if __name__ == '__main__':
    main()
