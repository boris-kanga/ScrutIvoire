import aioboto3
from botocore.exceptions import ClientError

class S3StorageAdapter:
    def __init__(self, endpoint_url, access_key, secret_key, region="us-east-1"):
        self.session = aioboto3.Session()
        self.config = {
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
        }

    async def create_bucket(self, bucket_name):
        """Crée un bucket s'il n'existe pas déjà."""
        async with self.session.client("s3", **self.config) as s3:
            try:
                await s3.head_bucket(Bucket=bucket_name)
            except ClientError:
                await s3.create_bucket(Bucket=bucket_name)
                print(f"Bucket '{bucket_name}' créé.")

    async def upload(self, bucket, local_path, remote_name):
        """Upload un fichier local vers le bucket."""
        async with self.session.client("s3", **self.config) as s3:
            await s3.upload_file(local_path, bucket, remote_name)
            return f"Uploaded {remote_name}"

    async def download(self, bucket, remote_name, local_path):
        """Télécharge un objet du bucket vers le disque local."""
        async with self.session.client("s3", **self.config) as s3:
            await s3.download_file(bucket, remote_name, local_path)

    async def list_files(self, bucket, prefix=""):
        """Liste les fichiers dans un bucket (optionnellement par dossier/prefix)."""
        async with self.session.client("s3", **self.config) as s3:
            paginator = s3.get_paginator("list_objects_v2")
            files = []
            async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    files.append(obj["Key"])
            return files

    async def delete(self, bucket, remote_name):
        """Supprime un fichier du bucket."""
        async with self.session.client("s3", **self.config) as s3:
            await s3.delete_object(Bucket=bucket, Key=remote_name)

    async def get_presigned_url(self, bucket, remote_name, expires=3600):
        """Génère un lien temporaire pour accéder au fichier via navigateur."""
        async with self.session.client("s3", **self.config) as s3:
            return await s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket, 'Key': remote_name},
                ExpiresIn=expires
            )
