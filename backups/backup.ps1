$backupDir = "C:\Diplom\spb_places\backups"
if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir }

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = "$backupDir\spb_places_backup_$timestamp.sql"

docker exec -t spb_postgres pg_dump -U apollinaria --encoding=UTF8 spb_places | Out-File -Encoding utf8 $backupFile
