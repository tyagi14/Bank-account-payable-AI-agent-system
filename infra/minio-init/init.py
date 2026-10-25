import os

from minio import Minio
from minio.credentials import StaticProvider
from minio.minioadmin import MinioAdmin
from minio.commonconfig import COMPLIANCE
from minio.objectlockconfig import DAYS, ObjectLockConfig

client = Minio("minio:9000", os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"], secure=False)

for bucket in ("langfuse", "invoice-inbox"):
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        print(f"created bucket {bucket}")

# Object lock can only be enabled at bucket creation time; it also forces versioning on.
if not client.bucket_exists("audit-log"):
    client.make_bucket("audit-log", object_lock=True)
    print("created bucket audit-log with object lock")
days = int(os.environ["AUDIT_RETENTION_DAYS"])
client.set_object_lock_config("audit-log", ObjectLockConfig(COMPLIANCE, days, DAYS))
print(f"audit-log default retention: COMPLIANCE {days} day(s)")

# Least-privilege identity for custodian-audit-log: it can append and read audit objects and set retention
# on what it writes (COMPLIANCE can be extended, never shortened), but holds no delete rights.
admin = MinioAdmin(endpoint="minio:9000", credentials=StaticProvider(os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"]), secure=False)
admin.policy_add("audit-append-only", policy={
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketObjectLockConfiguration"], "Resource": ["arn:aws:s3:::audit-log"]},
        {"Effect": "Allow", "Action": ["s3:PutObject", "s3:PutObjectRetention", "s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectRetention"], "Resource": ["arn:aws:s3:::audit-log/*"]},
    ],
})
admin.user_add("audit-writer", os.environ["AUDIT_MINIO_PASSWORD"])
admin.attach_policy(["audit-append-only"], user="audit-writer") if "audit-append-only" not in admin.user_info("audit-writer") else None
print("audit-writer user ready with audit-append-only policy")

admin.policy_add("langfuse-bucket", policy={
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetBucketLocation", "s3:ListBucket"], "Resource": ["arn:aws:s3:::langfuse"]},
        {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"], "Resource": ["arn:aws:s3:::langfuse/*"]},
    ],
})
admin.user_add("langfuse", os.environ["LANGFUSE_MINIO_PASSWORD"])
admin.attach_policy(["langfuse-bucket"], user="langfuse") if "langfuse-bucket" not in admin.user_info("langfuse") else None
print("langfuse user ready with langfuse-bucket policy")
