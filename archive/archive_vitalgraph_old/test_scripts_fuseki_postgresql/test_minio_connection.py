#!/usr/bin/env python3
"""
Test MinIO Connection and Basic Operations

This script tests:
1. MinIO server connectivity
2. Bucket creation
3. File upload
4. File download
5. File deletion
"""

import sys
from pathlib import Path
import io

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from minio import Minio
    from minio.error import S3Error
except ImportError:
    print("❌ minio package not installed. Install with: pip install minio")
    sys.exit(1)


def test_minio_connection():
    """Test MinIO connection and basic operations."""
    
    print("🧪 Testing MinIO Connection")
    print("=" * 80)
    
    # MinIO configuration (from vitalgraphdb-config.yaml)
    endpoint = "localhost:9000"
    access_key = "minioadmin"
    secret_key = "minioadmin"
    bucket_name = "vitalgraph-files-local"
    
    try:
        # 1. Initialize MinIO client
        print("\n1️⃣  Initializing MinIO client...")
        client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=False  # use_ssl: false
        )
        print(f"   ✅ Connected to MinIO at {endpoint}")
        
        # 2. Check if bucket exists, create if not
        print(f"\n2️⃣  Checking bucket '{bucket_name}'...")
        if client.bucket_exists(bucket_name):
            print(f"   ✅ Bucket '{bucket_name}' already exists")
        else:
            print(f"   📦 Creating bucket '{bucket_name}'...")
            client.make_bucket(bucket_name)
            print(f"   ✅ Bucket '{bucket_name}' created successfully")
        
        # 3. Upload a test file
        print("\n3️⃣  Testing file upload...")
        test_content = b"Hello from VitalGraph! This is a test file for MinIO."
        test_file_name = "test-file.txt"
        
        client.put_object(
            bucket_name,
            test_file_name,
            io.BytesIO(test_content),
            length=len(test_content),
            content_type="text/plain"
        )
        print(f"   ✅ Uploaded '{test_file_name}' ({len(test_content)} bytes)")
        
        # 4. List objects in bucket
        print(f"\n4️⃣  Listing objects in bucket '{bucket_name}'...")
        objects = list(client.list_objects(bucket_name))
        print(f"   📋 Found {len(objects)} object(s):")
        for obj in objects:
            print(f"      - {obj.object_name} ({obj.size} bytes, modified: {obj.last_modified})")
        
        # 5. Download the test file
        print(f"\n5️⃣  Testing file download...")
        response = client.get_object(bucket_name, test_file_name)
        downloaded_content = response.read()
        response.close()
        response.release_conn()
        
        if downloaded_content == test_content:
            print(f"   ✅ Downloaded '{test_file_name}' successfully")
            print(f"   ✅ Content matches: {downloaded_content.decode()}")
        else:
            print(f"   ❌ Content mismatch!")
            return False
        
        # 6. Get object stats
        print(f"\n6️⃣  Getting object metadata...")
        stat = client.stat_object(bucket_name, test_file_name)
        print(f"   📊 Object stats:")
        print(f"      - Size: {stat.size} bytes")
        print(f"      - Content-Type: {stat.content_type}")
        print(f"      - ETag: {stat.etag}")
        print(f"      - Last Modified: {stat.last_modified}")
        
        # 7. Generate presigned URL
        print(f"\n7️⃣  Testing presigned URL generation...")
        from datetime import timedelta
        url = client.presigned_get_object(bucket_name, test_file_name, expires=timedelta(hours=1))
        print(f"   ✅ Generated presigned URL (valid for 1 hour):")
        print(f"      {url[:80]}...")
        
        # 8. Delete test file
        print(f"\n8️⃣  Cleaning up test file...")
        client.remove_object(bucket_name, test_file_name)
        print(f"   ✅ Deleted '{test_file_name}'")
        
        # 9. Verify deletion
        remaining_objects = list(client.list_objects(bucket_name))
        print(f"   📋 Remaining objects: {len(remaining_objects)}")
        
        print("\n" + "=" * 80)
        print("✅ All MinIO tests passed successfully!")
        print("\n📊 Summary:")
        print("   ✅ Connection: Working")
        print("   ✅ Bucket operations: Working")
        print("   ✅ File upload: Working")
        print("   ✅ File download: Working")
        print("   ✅ File listing: Working")
        print("   ✅ Metadata retrieval: Working")
        print("   ✅ Presigned URLs: Working")
        print("   ✅ File deletion: Working")
        print("\n🎉 MinIO is ready for VitalGraph file storage!")
        
        return True
        
    except S3Error as e:
        print(f"\n❌ MinIO S3 Error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_minio_connection()
    sys.exit(0 if success else 1)
