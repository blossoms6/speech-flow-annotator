# Speech Flow 云服务器部署

本指南适用于 Ubuntu 24.04、2 vCPU、2 GiB 内存的单机试运行环境。该配置不安装 Whisper 自动转写；用户需要提供英文原文，或者使用“只有文稿”模式。

## 1. 等待服务器准备完成

在云厂商控制台等待实例从“准备中”变成“运行中”，并确认页面出现公网 IPv4。随后：

1. 设置服务器登录密码或 SSH 密钥。
2. 在服务器防火墙中只开放 TCP `22`、`80`、`443`，以及 UDP `443`。
3. 不要开放 `8765`，该端口只供 Docker 内部网络使用。

## 2. 连接服务器

在本机 PowerShell 中执行，替换成实际公网 IP：

```powershell
ssh root@服务器公网IP
```

如果云厂商提供的用户名不是 `root`，请使用控制台显示的用户名。

## 3. 给 2 GiB 服务器增加交换空间

先检查是否已有交换空间：

```bash
free -h
```

如果 Swap 为 0，执行：

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

交换空间不能替代内存，但能降低 Chromium 导出 PDF 或音频处理时被系统直接终止的概率。

## 4. 安装 Docker Engine

使用 Docker 官方 APT 仓库：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

## 5. 下载项目

项目推送到 GitHub 后，在服务器执行：

```bash
cd /opt
sudo git clone https://github.com/blossoms6/speech-flow-annotator.git speech-flow
cd /opt/speech-flow
```

如果仓库是私有仓库，需要配置 GitHub 身份验证，不能直接把访问令牌写在命令或聊天中。

## 6. 创建生产配置

```bash
sudo cp .env.production.example .env.production
sudo nano .env.production
```

首次只通过公网 IP 测试时保留：

```env
SITE_ADDRESS=:80
SFA_SECURE_COOKIES=false
```

有域名并已把 DNS 指向服务器后，改成：

```env
SITE_ADDRESS=speech.example.com
SFA_SECURE_COOKIES=true
```

将 `speech.example.com` 替换为实际域名。Caddy 会自动申请和续期 HTTPS 证书。

## 7. 构建并启动

```bash
sudo docker compose build
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 app
```

首次构建需要下载 Python、Chromium、中文字体和依赖，耗时取决于服务器网络。

通过 IP 测试：

```text
http://服务器公网IP
```

使用域名和 HTTPS 后：

```text
https://你的域名
```

## 8. 创建管理员

```bash
cd /opt/speech-flow
sudo docker compose exec app python scripts/create-admin.py
```

按提示输入用户名和密码。然后在 `/login` 登录，并访问 `/admin`。

## 9. 更新版本

```bash
cd /opt/speech-flow
sudo git pull --ff-only
sudo docker compose build
sudo docker compose up -d
sudo docker image prune -f
```

## 10. 备份

尽量在没有任务运行时执行：

```bash
cd /opt/speech-flow
sudo docker compose exec app python scripts/backup.py
sudo mkdir -p backups
sudo docker compose cp app:/data/backups/. ./backups/
```

备份目录包含 SQLite 账户数据库和任务文件压缩包。请定期把 `backups/` 下载到另一台设备。

## 常用排查命令

```bash
sudo docker compose ps
sudo docker compose logs --tail=200 app
sudo docker compose logs --tail=200 caddy
df -h
free -h
```

停止网站：

```bash
sudo docker compose down
```

`docker compose down` 不会删除命名数据卷。不要执行 `docker compose down -v`，否则会删除账户和任务数据。
