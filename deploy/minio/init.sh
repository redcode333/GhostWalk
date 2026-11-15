#!/bin/sh
# One-shot: create HydraDB's bucket in MinIO and a user that can only touch that bucket. Idempotent. Credentials come from the environment, never from this file.
set -eu
: "${MINIO_ROOT_USER:?}" "${MINIO_ROOT_PASSWORD:?}" "${HYDRA_S3_KEY:?}" "${HYDRA_S3_SECRET:?}" "${BUCKET:?}"
for _ in $(seq 1 60); do
  mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 && break
  sleep 1
done
mc mb --ignore-existing "local/$BUCKET"
cat > /tmp/policy.json <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:*"],"Resource":["arn:aws:s3:::$BUCKET","arn:aws:s3:::$BUCKET/*"]}]}
JSON
mc admin policy create local hydradb-rw /tmp/policy.json >/dev/null 2>&1 || mc admin policy create local hydradb-rw /tmp/policy.json || true
mc admin user add local "$HYDRA_S3_KEY" "$HYDRA_S3_SECRET" >/dev/null 2>&1 || true
mc admin policy attach local hydradb-rw --user "$HYDRA_S3_KEY" >/dev/null 2>&1 || true
echo "bucket $BUCKET ready; user ${HYDRA_S3_KEY%????????????????????????}... limited to it"
