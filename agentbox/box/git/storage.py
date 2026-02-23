"""
Pluggable storage backends for GitBox persistence.

Each backend implements the same async interface for reading/writing
individual files to a permanent store. The git objects, refs, and
working tree files are stored individually (not as a tar/zip), enabling
direct asset access and incremental sync.

Storage layout:
    {prefix}/{repo_id}/workspace/report.md
    {prefix}/{repo_id}/workspace/chart.png
    {prefix}/{repo_id}/.git/refs/heads/main
    {prefix}/{repo_id}/.git/objects/ab/cdef1234...
"""

import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path


class StorageBackend(ABC):
    """Abstract base class for git repo storage backends."""

    @abstractmethod
    async def exists(self, repo_id: str) -> bool:
        """Check if a repo exists in the store."""
        ...

    @abstractmethod
    async def list_files(self, repo_id: str, prefix: str = "") -> list[str]:
        """List all file paths in a repo (relative to repo root).

        Args:
            repo_id: Repository identifier.
            prefix: Optional path prefix filter (e.g., ".git/objects/").

        Returns:
            List of relative paths.
        """
        ...

    @abstractmethod
    async def read_file(self, repo_id: str, path: str) -> bytes | None:
        """Read a file from the store. Returns None if not found."""
        ...

    @abstractmethod
    async def write_file(self, repo_id: str, path: str, data: bytes) -> None:
        """Write a file to the store (creates parent dirs as needed)."""
        ...

    @abstractmethod
    async def delete_file(self, repo_id: str, path: str) -> None:
        """Delete a file from the store."""
        ...

    @abstractmethod
    async def delete_repo(self, repo_id: str) -> None:
        """Delete an entire repo from the store."""
        ...


class LocalStorageBackend(StorageBackend):
    """Store repos on the local filesystem. For development and testing.

    Layout:
        {base_path}/{repo_id}/workspace/file.txt
        {base_path}/{repo_id}/.git/objects/...
    """

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _repo_path(self, repo_id: str) -> Path:
        # Sanitize repo_id to prevent path traversal
        safe_id = repo_id.replace("..", "").replace("/", "_").replace("\\", "_")
        return self.base_path / safe_id

    async def exists(self, repo_id: str) -> bool:
        return self._repo_path(repo_id).is_dir()

    async def list_files(self, repo_id: str, prefix: str = "") -> list[str]:
        repo_dir = self._repo_path(repo_id)
        if not repo_dir.is_dir():
            return []

        search_dir = repo_dir / prefix if prefix else repo_dir
        if not search_dir.is_dir():
            return []

        result = []
        for path in search_dir.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(repo_dir))
                result.append(rel)
        return sorted(result)

    async def read_file(self, repo_id: str, path: str) -> bytes | None:
        file_path = self._repo_path(repo_id) / path
        if not file_path.is_file():
            return None
        return file_path.read_bytes()

    async def write_file(self, repo_id: str, path: str, data: bytes) -> None:
        file_path = self._repo_path(repo_id) / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)

    async def delete_file(self, repo_id: str, path: str) -> None:
        file_path = self._repo_path(repo_id) / path
        if file_path.is_file():
            file_path.unlink()

    async def delete_repo(self, repo_id: str) -> None:
        repo_dir = self._repo_path(repo_id)
        if repo_dir.is_dir():
            shutil.rmtree(repo_dir)


class S3StorageBackend(StorageBackend):
    """Store repos in S3 or S3-compatible storage (MinIO, etc.).

    Layout:
        s3://{bucket}/{prefix}/{repo_id}/workspace/file.txt
        s3://{bucket}/{prefix}/{repo_id}/.git/objects/...

    Requires boto3. Set s3_endpoint for MinIO or other S3-compatible stores.
    """

    def __init__(self, bucket: str, prefix: str = "repos/",
                 endpoint_url: str | None = None,
                 region_name: str | None = None):
        try:
            import boto3
        except ImportError:
            raise ImportError("boto3 is required for S3StorageBackend. pip install boto3")

        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""

        kwargs = {}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if region_name:
            kwargs["region_name"] = region_name

        self._s3 = boto3.client("s3", **kwargs)

    def _key(self, repo_id: str, path: str = "") -> str:
        safe_id = repo_id.replace("..", "").replace("\\", "_")
        if path:
            return f"{self.prefix}{safe_id}/{path}"
        return f"{self.prefix}{safe_id}/"

    async def exists(self, repo_id: str) -> bool:
        # Check if any objects exist with this prefix
        resp = self._s3.list_objects_v2(
            Bucket=self.bucket,
            Prefix=self._key(repo_id),
            MaxKeys=1,
        )
        return resp.get("KeyCount", 0) > 0

    async def list_files(self, repo_id: str, prefix: str = "") -> list[str]:
        full_prefix = self._key(repo_id, prefix)
        repo_prefix = self._key(repo_id)
        result = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                rel = obj["Key"][len(repo_prefix):]
                result.append(rel)
        return sorted(result)

    async def read_file(self, repo_id: str, path: str) -> bytes | None:
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=self._key(repo_id, path))
            return resp["Body"].read()
        except self._s3.exceptions.NoSuchKey:
            return None
        except Exception:
            return None

    async def write_file(self, repo_id: str, path: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=self._key(repo_id, path), Body=data)

    async def delete_file(self, repo_id: str, path: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=self._key(repo_id, path))

    async def delete_repo(self, repo_id: str) -> None:
        # Delete all objects with this prefix
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._key(repo_id)):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                self._s3.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
