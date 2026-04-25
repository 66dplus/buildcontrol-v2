# Deploy

```bash
cd "/Users/dmitrijrybkin/Documents/Claude Code/BuildControl_v2" && SSHPASS='3XaME1j%C0' sshpass -e /usr/bin/rsync -avz --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' --exclude='venv' --exclude='template_data' -e "ssh -o StrictHostKeyChecking=no" ./ root@162.120.19.127:/opt/buildcontrol/ && ssh root@162.120.19.127 "systemctl restart buildcontrol && systemctl status buildcontrol --no-pager"
```
curl http://162.120.19.127:8000/health