from typing import Protocol



class FileStorageProtocol(Protocol):
    def __init__(self, endpoint, *_, **__):
        pass

    async def create_bucket(self, bucket_name):
        pass

    async def file_exists(self, bucket, filename):
        pass

    async def upload(self, bucket, local_path, remote_name):
        pass

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

    async def delete_bucket(self, bucket_name):
        pass

    async def delete_all_storage(self):
        pass