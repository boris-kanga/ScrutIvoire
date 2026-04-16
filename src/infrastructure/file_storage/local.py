import os
import tempfile
import asyncio
import shutil
import aiofiles

from typing import Optional


class LocalStorageAdapter:
    def __init__(self, endpoint, *_, **__):
        self._lock: Optional[asyncio.Lock] = None
        self._base_folder = endpoint

    async def __aenter__(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        await self._lock.acquire()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._lock is not None:
            self._lock.release()

    async def create_bucket(self, bucket_name):
        """Crée un bucket s'il n'existe pas déjà."""
        async with self:
            os.makedirs(os.path.join(
                self._base_folder, bucket_name
            ), exist_ok=True)
            print(f"Bucket '{bucket_name}' créé.")

    async def upload(self, bucket, local_path, remote_name):
        """Upload un fichier local vers le bucket."""
        async with self:
            dest = str(
                os.path.join(
                    self._base_folder, bucket, remote_name
                )
            )
            if isinstance(local_path, str):
                shutil.copy(
                    str(local_path),
                    dest
                )
            else:
                async with aiofiles.open(dest, "wb") as fp:
                    await fp.write(fp.read())

    async def download(self, bucket, remote_name, local_path):
        """Télécharge un objet du bucket vers le disque local."""
        pass

    async def list_files(self, bucket, prefix=""):
        """Liste les fichiers dans un bucket (optionnellement par dossier/prefix)."""
        pass

    async def delete(self, bucket, remote_name):
        """Supprime un fichier du bucket."""
        pass

    async def get_presigned_url(self, bucket, remote_name, expires=3600):
        """Génère un lien temporaire pour accéder au fichier via navigateur."""
        pass
