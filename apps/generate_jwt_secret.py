#!/usr/bin/env python3
"""
JWT Secret Key Generator for VitalGraph

This script generates cryptographically secure JWT secret keys
for use in VitalGraph authentication.
"""

import secrets
import base64
import argparse


def generate_jwt_secret(length_bytes: int = 32) -> str:
    """
    Generate a cryptographically secure JWT secret key.
    
    Args:
        length_bytes: Length of the secret key in bytes (default: 32 = 256 bits)
        
    Returns:
        Base64 URL-safe encoded secret key
    """
    # Generate random bytes
    random_bytes = secrets.token_bytes(length_bytes)
    
    # Encode as base64 URL-safe string
    secret_key = base64.urlsafe_b64encode(random_bytes).decode('utf-8')
    
    return secret_key


def main():
    parser = argparse.ArgumentParser(
        description="Generate secure JWT secret keys for VitalGraph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_jwt_secret.py                    # Generate 256-bit key
  python generate_jwt_secret.py --length 64        # Generate 512-bit key
  python generate_jwt_secret.py --env-format       # Output in .env format
        """
    )
    
    parser.add_argument(
        '--length', '-l',
        type=int,
        default=32,
        help='Length of secret key in bytes (default: 32 = 256 bits)'
    )
    
    parser.add_argument(
        '--env-format', '-e',
        action='store_true',
        help='Output in .env file format'
    )
    
    parser.add_argument(
        '--count', '-c',
        type=int,
        default=1,
        help='Number of keys to generate (default: 1)'
    )
    
    args = parser.parse_args()
    
    # Validate key length
    if args.length < 16:
        print("⚠️  Warning: Key length less than 128 bits is not recommended for security")
    elif args.length >= 32:
        print(f"✅ Generating {args.length * 8}-bit JWT secret key(s)...")
    
    # Generate keys
    for i in range(args.count):
        secret_key = generate_jwt_secret(args.length)
        
        if args.env_format:
            print(f"JWT_SECRET_KEY={secret_key}")
        else:
            if args.count > 1:
                print(f"Key {i+1}: {secret_key}")
            else:
                print(secret_key)
    
    # Security reminder
    if not args.env_format:
        print("\n🔐 Security Reminders:")
        print("   • Keep this key secret and secure")
        print("   • Use different keys for dev/staging/production")
        print("   • Rotate keys regularly")
        print("   • Never commit keys to version control")


if __name__ == "__main__":
    main()
