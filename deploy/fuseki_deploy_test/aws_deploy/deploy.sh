#!/bin/bash
set -e

# Configuration
AWS_REGION=${AWS_REGION:-us-east-1}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}
ECR_REPOSITORY="vitalgraph-fuseki"
IMAGE_TAG=${IMAGE_TAG:-latest}
CLUSTER_NAME=${CLUSTER_NAME:-vitalgraph-cluster}
SERVICE_NAME=${SERVICE_NAME:-vitalgraph-fuseki-service}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
    exit 1
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    if ! command -v aws &> /dev/null; then
        error "AWS CLI is not installed"
    fi
    
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
    fi
    
    if [ -z "$AWS_ACCOUNT_ID" ]; then
        error "Could not determine AWS Account ID"
    fi
    
    log "Prerequisites check passed"
}

# Create ECR repository if it doesn't exist
create_ecr_repository() {
    log "Checking ECR repository..."
    
    if ! aws ecr describe-repositories --repository-names $ECR_REPOSITORY --region $AWS_REGION &> /dev/null; then
        log "Creating ECR repository: $ECR_REPOSITORY"
        aws ecr create-repository \
            --repository-name $ECR_REPOSITORY \
            --region $AWS_REGION \
            --image-scanning-configuration scanOnPush=true
    else
        log "ECR repository already exists: $ECR_REPOSITORY"
    fi
}

# Build and push Docker image
build_and_push_image() {
    log "Building Docker image..."
    
    # Build the image
    docker build -t $ECR_REPOSITORY:$IMAGE_TAG .
    
    # Tag for ECR
    ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG"
    docker tag $ECR_REPOSITORY:$IMAGE_TAG $ECR_URI
    
    # Login to ECR
    log "Logging in to ECR..."
    aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
    
    # Push image
    log "Pushing image to ECR..."
    docker push $ECR_URI
    
    log "Image pushed successfully: $ECR_URI"
}

# Deploy infrastructure using Python script
deploy_infrastructure() {
    log "Deploying infrastructure using Python script..."
    
    # Check if Python dependencies are installed
    if ! python3 -c "import boto3" &> /dev/null; then
        log "Installing Python dependencies..."
        pip3 install -r requirements.txt
    fi
    
    # Get VPC and subnet information
    if [ -z "$VPC_ID" ]; then
        log "Getting default VPC..."
        VPC_ID=$(aws ec2 describe-vpcs --filters "Name=is-default,Values=true" --query 'Vpcs[0].VpcId' --output text --region $AWS_REGION)
    fi
    
    if [ -z "$PRIVATE_SUBNETS" ]; then
        log "Getting private subnets..."
        PRIVATE_SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" "Name=map-public-ip-on-launch,Values=false" --query 'Subnets[].SubnetId' --output text --region $AWS_REGION | tr '\t' ',')
    fi
    
    if [ -z "$PUBLIC_SUBNETS" ]; then
        log "Getting public subnets..."
        PUBLIC_SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" "Name=map-public-ip-on-launch,Values=true" --query 'Subnets[].SubnetId' --output text --region $AWS_REGION | tr '\t' ',')
    fi
    
    # Run Python deployment script
    python3 aws_deploy.py \
        --region $AWS_REGION \
        --vpc-id $VPC_ID \
        --private-subnets $PRIVATE_SUBNETS \
        --public-subnets $PUBLIC_SUBNETS \
        --image-uri "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG"
    
    log "Infrastructure deployment completed"
}

# Main deployment function
main() {
    log "Starting VitalGraph Fuseki AWS deployment..."
    
    check_prerequisites
    create_ecr_repository
    build_and_push_image
    deploy_infrastructure
    
    log "Deployment completed successfully!"
    log "Image: $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG"
}

# Run main function
main "$@"
