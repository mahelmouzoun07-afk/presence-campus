# Programme la sauvegarde quotidienne dans le Planificateur de tâches Windows
# (pour un PC Windows + WSL, où le service cron de Linux ne démarre pas tout seul).
# À lancer UNE fois, dans PowerShell, après installer-sauvegarde.sh :
#   powershell -ExecutionPolicy Bypass -File "$HOME\Desktop\Presence-Ecole\outils\planifier-sauvegarde-windows.ps1"
$action = New-ScheduledTaskAction -Execute "wsl.exe" `
  -Argument "-d Ubuntu -- bash -lc 'bash ~/odoo-custom-addons/outils/sauvegarde.sh mon_ecole'"
$trigger = New-ScheduledTaskTrigger -Daily -At 2:30am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd
Register-ScheduledTask -TaskName "Presence-Ecole - sauvegarde" -Action $action -Trigger $trigger `
  -Settings $settings -Description "Sauvegarde chiffrée quotidienne de la base de l'école" -Force
Write-Host "Sauvegarde programmée chaque nuit à 2h30 (ou au prochain démarrage si le PC était éteint)."
