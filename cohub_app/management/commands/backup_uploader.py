"""
Utility for uploading backups to cloud storage.
Supports: AWS S3, Google Drive, local network

Установка для использования:
- AWS S3: pip install boto3
- Google Drive: pip install google-auth google-auth-httplib2 google-auth-oauthlib google-api-python-client
"""

import os
import logging
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)


class BackupUploader:
    """Base class for backup uploaders"""
    
    def upload(self, backup_path: str) -> bool:
        raise NotImplementedError


class S3Uploader(BackupUploader):
    """Upload backups to AWS S3"""
    
    def __init__(self):
        try:
            import boto3
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
                region_name=os.environ.get('AWS_S3_REGION', 'us-east-1'),
            )
            self.bucket = os.environ.get('AWS_S3_BUCKET')
        except ImportError:
            raise ImportError('boto3 is required for S3 uploads. Install with: pip install boto3')
    
    def upload(self, backup_path: str) -> bool:
        try:
            file_name = Path(backup_path).name
            self.s3_client.upload_file(
                backup_path,
                self.bucket,
                f'backups/{file_name}',
                ExtraArgs={'ServerSideEncryption': 'AES256'}
            )
            logger.info(f'Backup uploaded to S3: {file_name}')
            return True
        except Exception as e:
            logger.error(f'S3 upload failed: {e}')
            return False


class GoogleDriveUploader(BackupUploader):
    """Upload backups to Google Drive"""
    
    def __init__(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
            
            # Используйте service account JSON файл
            credentials = Credentials.from_service_account_file(
                os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', 'service_account.json')
            )
            self.drive_service = build('drive', 'v3', credentials=credentials)
        except ImportError:
            raise ImportError(
                'Google API client is required. Install with: '
                'pip install google-auth google-auth-httplib2 google-auth-oauthlib google-api-python-client'
            )
    
    def upload(self, backup_path: str) -> bool:
        try:
            file_name = Path(backup_path).name
            file_metadata = {'name': file_name}
            
            media = self._get_media_upload(backup_path)
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            logger.info(f'Backup uploaded to Google Drive: {file_name} ({file["id"]})')
            return True
        except Exception as e:
            logger.error(f'Google Drive upload failed: {e}')
            return False
    
    @staticmethod
    def _get_media_upload(backup_path):
        from googleapiclient.http import MediaFileUpload
        return MediaFileUpload(backup_path, mimetype='application/json', resumable=True)


class LocalNetworkUploader(BackupUploader):
    """Upload to local network (SMB/NFS share)"""
    
    def __init__(self):
        self.backup_path = os.environ.get('BACKUP_NETWORK_PATH')
        if not self.backup_path:
            raise ValueError('BACKUP_NETWORK_PATH environment variable is required')
    
    def upload(self, backup_path: str) -> bool:
        try:
            import shutil
            dest = Path(self.backup_path) / Path(backup_path).name
            shutil.copy2(backup_path, dest)
            logger.info(f'Backup copied to network: {dest}')
            return True
        except Exception as e:
            logger.error(f'Network backup failed: {e}')
            return False


def get_uploader(service: str = None) -> BackupUploader:
    """Factory function to get appropriate uploader"""
    service = service or os.environ.get('BACKUP_UPLOAD_SERVICE', '')
    
    if service.lower() == 's3':
        return S3Uploader()
    elif service.lower() == 'google_drive':
        return GoogleDriveUploader()
    elif service.lower() == 'network':
        return LocalNetworkUploader()
    else:
        raise ValueError(f'Unknown backup service: {service}')


# Пример использования (можно добавить в backup_data command):
"""
from django.core.management import call_command
from .backup_uploader import get_uploader

# После создания backup файла:
backup_file = 'backups/cohub-backup-20240328-140000.json.gz'
if os.environ.get('BACKUP_UPLOAD_SERVICE'):
    uploader = get_uploader()
    uploader.upload(backup_file)
"""
