# VitalGraph Fuseki AWS ECS Deployment

This directory contains everything needed to deploy VitalGraph Fuseki to AWS ECS with persistent storage using EFS.

## Architecture

- **ECS Fargate**: Serverless container hosting
- **EFS**: Persistent storage for TDB2 database files
- **Application Load Balancer**: HTTP/HTTPS access with health checks
- **CloudWatch**: Logging and monitoring
- **Single Instance**: Designed for single database instance (DesiredCount=1)

## Files

- `Dockerfile` - Production-ready container image
- `entrypoint.sh` - Container startup script with EFS support
- `config/` - Fuseki configuration files (config.ttl, shiro.ini)
- `task-definition.json` - ECS task definition template
- `cloudformation.yaml` - Complete AWS infrastructure
- `deploy.sh` - Automated deployment script
- `docker-compose.yml` - Local testing

## Quick Deployment

### Prerequisites

1. AWS CLI configured with appropriate permissions
2. Docker installed
3. VPC with public and private subnets

### Deploy Infrastructure

```bash
# Install Python dependencies
pip3 install -r requirements.txt

# Deploy using Python script
python3 aws_deploy.py \
  --region us-east-1 \
  --vpc-id vpc-xxxxxxxx \
  --private-subnets subnet-xxxxxxxx,subnet-yyyyyyyy \
  --public-subnets subnet-aaaaaaaa,subnet-bbbbbbbb
```

### Deploy Application

```bash
# Set environment variables
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Run deployment script
./deploy.sh
```

## Configuration

### Environment Variables

- `MEMORY_LIMIT` - Container memory limit in MB (default: 2048)
- `EFS_MOUNT_POINT` - EFS mount path (default: /efs)
- `JAVA_OPTIONS` - JVM options for Fuseki

### EFS Storage

The deployment uses EFS for persistent storage:
- Database files stored in `/efs/databases/`
- Automatic directory creation on startup
- Encryption in transit and at rest
- Provisioned throughput for consistent performance

### Authentication

Uses the same Shiro configuration as local deployment:
- `admin` / `admin123`
- `vitalgraph_user` / `vitalgraph_pass`
- `readonly_user` / `readonly_pass`

## Accessing the Service

After deployment, access Fuseki via the Application Load Balancer:

```bash
# Get ALB DNS name
aws cloudformation describe-stacks \
  --stack-name vitalgraph-fuseki \
  --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' \
  --output text

# Test connectivity
curl http://ALB_DNS_NAME/$/ping

# Query with authentication
curl -u admin:admin123 -X POST http://ALB_DNS_NAME/vitalgraph/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT * WHERE { ?s ?p ?o } LIMIT 5"
```

## Monitoring

### CloudWatch Logs

Logs are available in CloudWatch:
- Log Group: `/ecs/vitalgraph-fuseki`
- Stream: `ecs/fuseki/TASK_ID`

### Health Checks

- **Container Health**: `curl -f http://localhost:3030/$/ping`
- **ALB Health**: Same endpoint via load balancer
- **ECS Service**: Monitors container health and restarts if needed

### Metrics

Monitor these CloudWatch metrics:
- `AWS/ECS/CPUUtilization`
- `AWS/ECS/MemoryUtilization`
- `AWS/ApplicationELB/TargetResponseTime`
- `AWS/EFS/DataReadIOBytes`
- `AWS/EFS/DataWriteIOBytes`

## Scaling Considerations

**Important**: This deployment is designed for a single Fuseki instance because:
- TDB2 database files are not designed for concurrent write access
- Multiple instances would cause data corruption
- For high availability, consider:
  - EFS backup and restore
  - Blue/green deployments
  - Read replicas (if supported by your use case)

## Security

### Network Security

- ECS tasks in private subnets
- ALB in public subnets
- Security groups restrict access:
  - ALB: HTTP/HTTPS from internet
  - ECS: Port 3030 from ALB only
  - EFS: NFS from ECS only

### Data Security

- EFS encryption at rest and in transit
- IAM roles with least privilege
- Shiro authentication for Fuseki endpoints
- Optional HTTPS with ACM certificate

## Troubleshooting

### Common Issues

1. **Task fails to start**
   ```bash
   # Check ECS service events
   aws ecs describe-services --cluster vitalgraph-cluster --services vitalgraph-fuseki-service
   
   # Check task logs
   aws logs get-log-events --log-group-name /ecs/vitalgraph-fuseki --log-stream-name STREAM_NAME
   ```

2. **EFS mount issues**
   ```bash
   # Verify EFS mount targets
   aws efs describe-mount-targets --file-system-id fs-xxxxxxxx
   
   # Check security group rules
   aws ec2 describe-security-groups --group-ids sg-xxxxxxxx
   ```

3. **Health check failures**
   ```bash
   # Test health endpoint directly
   curl -f http://ALB_DNS_NAME/$/ping
   
   # Check target group health
   aws elbv2 describe-target-health --target-group-arn TARGET_GROUP_ARN
   ```

### Useful Commands

```bash
# View service status
aws ecs describe-services --cluster vitalgraph-cluster --services vitalgraph-fuseki-service

# View running tasks
aws ecs list-tasks --cluster vitalgraph-cluster --service-name vitalgraph-fuseki-service

# View task definition
aws ecs describe-task-definition --task-definition vitalgraph-fuseki

# Update service (after new image push)
aws ecs update-service --cluster vitalgraph-cluster --service vitalgraph-fuseki-service --force-new-deployment

# View logs
aws logs tail /ecs/vitalgraph-fuseki --follow
```

## Cost Optimization

- **Fargate**: Pay only for running time
- **EFS**: Provisioned throughput can be adjusted based on usage
- **ALB**: Consider using NLB for lower cost if HTTP features not needed
- **CloudWatch**: Set appropriate log retention periods

## Backup Strategy

### EFS Backup

```bash
# Enable automatic backups
aws efs put-backup-policy --file-system-id fs-xxxxxxxx --backup-policy Status=ENABLED

# Manual backup
aws efs create-backup-vault --backup-vault-name vitalgraph-fuseki-backup
```

### Database Export

```bash
# Export data via SPARQL
curl -u admin:admin123 -X POST http://ALB_DNS_NAME/vitalgraph/sparql \
  -H "Accept: application/n-triples" \
  -d "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }" > backup.nt
```

## Updates and Maintenance

1. **Update Fuseki version**: Modify Dockerfile and rebuild
2. **Update configuration**: Modify config files and redeploy
3. **Scale resources**: Update CloudFormation template
4. **Security patches**: Rebuild container with latest base image

This deployment provides a production-ready, secure, and scalable Fuseki instance suitable for VitalGraph workloads on AWS.
