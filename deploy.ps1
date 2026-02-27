# PowerShell deploy helper for Railway
git add .
try {
    git commit -m "prepare for deploy"
} catch {}

git push origin main

if (Get-Command railway -ErrorAction SilentlyContinue) {
    Write-Host "Running Railway migration commands..."
    railway run python manage.py migrate
    railway run python manage.py collectstatic --noinput
} else {
    Write-Host "Railway CLI not found; install 'npm i -g @railway/cli'"
}