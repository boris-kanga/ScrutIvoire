import aioboto3
from botocore.exceptions import ClientError

class S3StorageAdapter:
    def __init__(self, endpoint, access_key, secret_key, region="us-east-1", **_):
        self.session = aioboto3.Session()
        self.config = {
            "endpoint_url": endpoint,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
        }

    async def delete_bucket(self, bucket_name):
        async with self.session.client("s3", **self.config) as s3:
            try:
                paginator = s3.get_paginator('list_object_versions')
                async for page in paginator.paginate(Bucket=bucket_name):
                    # Supprimer les versions d'objets
                    versions = page.get('Versions', [])
                    # Supprimer les "Delete Markers" (souvent ce qui bloque la suppression)
                    markers = page.get('DeleteMarkers', [])

                    for item in versions + markers:
                        await s3.delete_object(
                            Bucket=bucket_name,
                            Key=item['Key'],
                            VersionId=item['VersionId']
                        )
            except Exception:
                pass
            # 3. Supprimer le bucket maintenant qu'il est réellement vide
            try:
                await s3.delete_bucket(Bucket=bucket_name)
            except Exception:
                pass

    async def delete_all_storage(self):
        async with self.session.client("s3", **self.config) as s3:
            resp = await s3.list_buckets()
            buckets = resp.get('Buckets', [])
            for b in buckets:
                name = b['Name']
                try:
                    paginator = s3.get_paginator('list_object_versions')
                    async for page in paginator.paginate(Bucket=name):
                        versions = page.get('Versions', [])
                        markers = page.get('DeleteMarkers', [])

                        for item in versions + markers:
                            await s3.delete_object(
                                Bucket=name,
                                Key=item['Key'],
                                VersionId=item['VersionId']
                            )
                except Exception:
                    pass
                # 3. Supprimer le bucket maintenant qu'il est réellement vide
                try:
                    await s3.delete_bucket(Bucket=name)
                except Exception:
                    pass

    async def file_exists(self, bucket_name, filename):
        async with self.session.client("s3", **self.config) as s3:
            try:
                await s3.head_object(Bucket=bucket_name, Key=filename)
                return True
            except ClientError:
                return False

    async def create_bucket(self, bucket_name):
        """Crée un bucket s'il n'existe pas déjà."""
        async with self.session.client("s3", **self.config) as s3:
            try:
                await s3.head_bucket(Bucket=bucket_name)
            except ClientError:
                await s3.create_bucket(Bucket=bucket_name)
                print(f"Bucket '{bucket_name}' créé.")

    async def upload(self, bucket, file_source, remote_name):
        """
        Upload un fichier vers S3.
        file_source peut être :
        1. Un chemin local (str) -> on utilise upload_file
        2. Un objet file-like (ex: request.files['file']) -> on utilise put_object
        """
        async with self.session.client("s3", **self.config) as s3:
            try:
                # verifier si le bucket exists
                await s3.head_bucket(Bucket=bucket)
            except ClientError:
                # creer sinon
                await s3.create_bucket(Bucket=bucket)
                print(f"Bucket '{bucket}' créé.")
            if isinstance(file_source, str):
                # Cas d'un fichier local sur le disque
                await s3.upload_file(file_source, bucket, remote_name)
            else:
                # Cas d'un objet FileStorage (Flask) ou BytesIO
                # On lit le contenu du stream
                await s3.put_object(Bucket=bucket, Key=remote_name,
                                    Body=file_source)

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
