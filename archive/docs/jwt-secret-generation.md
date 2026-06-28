# JWT Secret Key Generation for VitalGraph

## Overview
VitalGraph uses JWT tokens for authentication, which require a secure secret key for signing and verification.

## Environment Configuration

### Development
The `.env` file contains a development JWT secret key:
```bash
JWT_SECRET_KEY=vitalgraph-super-secret-jwt-key-change-in-production-2025
```

### Production
**⚠️ IMPORTANT**: Always generate a new, secure JWT secret key for production deployments.

## Generating Secure JWT Secret Keys

### Method 1: Using Python (Recommended)
```python
import secrets
import base64

# Generate a 256-bit (32-byte) random key
secret_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')
print(f"JWT_SECRET_KEY={secret_key}")
```

### Method 2: Using OpenSSL
```bash
openssl rand -base64 32
```

### Method 3: Using Node.js
```javascript
const crypto = require('crypto');
const secretKey = crypto.randomBytes(32).toString('base64url');
console.log(`JWT_SECRET_KEY=${secretKey}`);
```

## Security Requirements

### Key Length
- **Minimum**: 256 bits (32 bytes)
- **Recommended**: 512 bits (64 bytes) for enhanced security

### Key Properties
- ✅ Cryptographically random
- ✅ Base64 URL-safe encoded
- ✅ Unique per deployment
- ✅ Never shared or committed to version control

## Deployment Configuration

### Docker Compose
The JWT secret is configured via environment variable:
```yaml
environment:
  - JWT_SECRET_KEY=${JWT_SECRET_KEY:-vitalgraph-default-jwt-secret-key}
```

### Environment File
Add to your production `.env` file:
```bash
JWT_SECRET_KEY=your-generated-secret-key-here
```

### Kubernetes
For Kubernetes deployments, use secrets:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: vitalgraph-jwt-secret
type: Opaque
data:
  jwt-secret-key: <base64-encoded-secret>
```

## Security Best Practices

1. **Rotate Keys Regularly**: Change JWT secret keys periodically
2. **Environment Isolation**: Use different keys for dev/staging/production
3. **Secure Storage**: Store keys in secure secret management systems
4. **Access Control**: Limit access to JWT secret keys
5. **Monitoring**: Monitor for unauthorized token usage

## Token Configuration

Current JWT settings in VitalGraph:
- **Access Token Expiry**: 30 minutes
- **Refresh Token Expiry**: 7 days
- **Algorithm**: HS256 (HMAC with SHA-256)

## Troubleshooting

### Invalid Token Errors
If you see "Invalid token" errors after changing the JWT secret:
1. All existing tokens become invalid
2. Users need to log in again
3. WebSocket connections will reconnect automatically

### Key Rotation Process
1. Generate new JWT secret key
2. Update environment variable
3. Restart application
4. Notify users of required re-authentication

## Example Production Setup

```bash
# Generate new secret key
python3 -c "import secrets, base64; print('JWT_SECRET_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

# Update .env file
echo "JWT_SECRET_KEY=<generated-key>" >> .env

# Restart application
docker-compose up --build
```
