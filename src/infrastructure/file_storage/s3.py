import json
from urllib.parse import urlparse

import aioboto3
from botocore.exceptions import ClientError


class S3StorageAdapter:
    def __init__(self, access_key, secret_key, endpoint="", region="us-east-1", public_url="", **_):
        self.session    = aioboto3.Session()
        self.region     = region
        self.public_url = public_url.rstrip("/")
        self.config     = {
            "endpoint_url":          endpoint.rstrip("/"),
            "aws_access_key_id":     access_key,
            "aws_secret_access_key": secret_key,
            "region_name":           region,
        }
        # Détection automatique AWS vs MinIO/autre
        self._is_aws = not endpoint

        self._endpoint_host = urlparse(endpoint).netloc
        self._public_host = urlparse(public_url).netloc

    def _object_url(self, bucket: str, key: str) -> str:
        """Construit l'URL publique d'un objet."""
        if self.public_url:
            return f"{self.public_url}/{bucket}//{key}"
        elif self._is_aws:
            return f"https://{bucket}.s3.{self.region}.amazonaws.com/{key}"
        else:
            base = self.config["endpoint_url"].rstrip("/")
            return f"{base}/{bucket}/{key}"

    async def disable_block_public_access(self, bucket: str):
        """Requis sur AWS avant de mettre une policy publique."""
        async with self.session.client("s3", **self.config) as s3:
            await s3.put_public_access_block(
                Bucket=bucket,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": False,
                    "IgnorePublicAcls": False,
                    "BlockPublicPolicy": False,
                    "RestrictPublicBuckets": False,
                }
            )

    async def set_public(self, bucket: str, prefix: str=None):
        """
        Rend public uniquement les objets sous un prefix.
        ex: prefix="crops/" → seul bucket/crops/* est public
        """
        if self._is_aws:
            await self.disable_block_public_access(bucket)

        ressource = f"{bucket}"
        if prefix is not None:
            ressource = f"{ressource}/{prefix.strip('/')}"

        policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{ressource}/*"
            }]
        })
        async with self.session.client("s3", **self.config) as s3:
            await s3.put_bucket_policy(Bucket=bucket, Policy=policy)

    async def upload(self, bucket, file_source, remote_name, content_type=None, public=False, retrieve_url=False):
        async with self.session.client("s3", **self.config) as s3:
            # Créer le bucket si nécessaire
            try:
                await s3.head_bucket(Bucket=bucket)
            except ClientError:
                await s3.create_bucket(Bucket=bucket)

            # Upload
            extra_args = {}
            if public and self._is_aws:
                extra_args["ACL"] = "public-read"  # AWS uniquement — MinIO gère au niveau bucket

            if isinstance(file_source, str):
                await s3.upload_file(file_source, bucket, remote_name, ExtraArgs=extra_args or None)
            else:
                body = file_source if not isinstance(file_source, bytes) else file_source
                await s3.put_object(
                    Bucket=bucket,
                    Key=remote_name,
                    Body=body,
                    ContentType=content_type or "application/octet-stream",
                    **extra_args,
                )

            # Retourner l'URL
            if public:
                return self._object_url(bucket, remote_name)
            else:
                if retrieve_url:
                    url = await s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": bucket, "Key": remote_name},
                        ExpiresIn=60 * 60 * 24 * 7,  # 7 jours
                    )
                    if self._is_aws:
                        return url
                    return str(url).replace(self._endpoint_host, self._public_host, 1)
            return None


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
            url = await s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket, 'Key': remote_name},
                ExpiresIn=expires
            )
            if self._is_aws:
                return url
            return str(url).replace(self._endpoint_host, self._public_host, 1)
