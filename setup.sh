#!/bin/bash

# Exit on any error
set -e

# Configuration variables (modify these as needed)
DOMAIN="datalyticx.com"  # Your Cloudflare domain
SUBDOMAIN="sensors"   # Subdomain for the tunnel (e.g., sensors.example.com)
TUNNEL_NAME="rpi-sensor-tunnel"  # Name for the Cloudflare tunnel
SERVER_PORT=8000  # Port where FastAPI server runs
PI_USER="dataalt"  # Raspberry Pi username (change if different)
WORKDIR="/home/$PI_USER/sensor-server"  # Working directory for server and configs
CONFIG_DIR="/home/$PI_USER/.cloudflared"
VENV_DIR="$WORKDIR/venv"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting setup for FastAPI server and Cloudflare Tunnel...${NC}"

# Step 1: Update system and install dependencies
echo -e "${GREEN}Installing system dependencies...${NC}"
sudo apt update
sudo apt install -y python3 python3-pip python3-venv wget

# Step 2: Create working directory
echo -e "${GREEN}Setting up working directory at $WORKDIR...${NC}"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

# Step 3: Copy server.py and requirements.txt (assuming they are in the current directory)
if [ ! -f "server.py" ] || [ ! -f "requirements.txt" ]; then
    echo -e "${RED}Error: server.py or requirements.txt not found in current directory!${NC}"
    exit 1
fi
cp server.py requirements.txt "$WORKDIR/"

# Step 4: Create and activate virtual environment
echo -e "${GREEN}Creating Python virtual environment...${NC}"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Step 5: Install Python dependencies
echo -e "${GREEN}Installing Python packages from requirements.txt...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# Step 6: Install cloudflared
echo -e "${GREEN}Installing cloudflared...${NC}"
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ]; then
    CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
elif [ "$ARCH" = "arm" ]; then
    CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm"
else
    echo -e "${RED}Unsupported architecture: $ARCH${NC}"
    exit 1
fi

wget "$CLOUDFLARED_URL" -O cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/cloudflared

# Verify cloudflared installation
cloudflared --version

# Step 7: Authenticate with Cloudflare
echo -e "${GREEN}Authenticating with Cloudflare (please follow the browser prompt)...${NC}"
cloudflared login
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/cert.pem" ]; then
    echo -e "${RED}Error: Cloudflare authentication failed, cert.pem not found!${NC}"
    exit 1
fi

# Step 8: Create Cloudflare Tunnel
echo -e "${GREEN}Creating Cloudflare Tunnel: $TUNNEL_NAME...${NC}"
cloudflared tunnel create "$TUNNEL_NAME"
TUNNEL_ID=$(cat "$CONFIG_DIR"/*.json | grep '"TunnelID"' | cut -d'"' -f4)
if [ -z "$TUNNEL_ID" ]; then
    echo -e "${RED}Error: Failed to retrieve Tunnel ID!${NC}"
    exit 1
fi
echo -e "${GREEN}Tunnel ID: $TUNNEL_ID${NC}"

# Step 9: Create Cloudflare Tunnel configuration
echo -e "${GREEN}Creating Cloudflare Tunnel configuration...${NC}"
cat > "$CONFIG_DIR/config.yml" << EOL
tunnel: $TUNNEL_ID
credentials-file: $CONFIG_DIR/$TUNNEL_ID.json
ingress:
  - hostname: $SUBDOMAIN.$DOMAIN
    service: http://localhost:$SERVER_PORT
  - service: http_status:404
EOL

# Step 10: Create DNS record (manual step reminder)
echo -e "${GREEN}Please create a CNAME record in Cloudflare DNS:${NC}"
echo "  Type: CNAME"
echo "  Name: $SUBDOMAIN"
echo "  Target: $TUNNEL_ID.cfargotunnel.com"
echo "  Proxy status: Proxied"
echo -e "${GREEN}Go to Cloudflare Dashboard > DNS > Records > Add record to set this up.${NC}"
echo -e "${GREEN}Press Enter to continue after creating the DNS record...${NC}"
read

# Step 11: Install cloudflared as a system service
echo -e "${GREEN}Installing cloudflared as a system service...${NC}"
sudo cloudflared service install --config "$CONFIG_DIR/config.yml"

# Step 12: Start and enable cloudflared service
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
sudo systemctl status cloudflared --no-pager

# Step 13: Create systemd service for FastAPI server
echo -e "${GREEN}Creating systemd service for FastAPI server...${NC}"
sudo bash -c "cat > /etc/systemd/system/sensor-server.service" << EOL
[Unit]
Description=FastAPI Sensor Server
After=network.target

[Service]
User=$PI_USER
WorkingDirectory=$WORKDIR
Environment="PATH=$VENV_DIR/bin"
ExecStart=$VENV_DIR/bin/uvicorn server:app --host 0.0.0.0 --port $SERVER_PORT
Restart=always

[Install]
WantedBy=multi-user.target
EOL

# Step 14: Start and enable FastAPI server service
sudo systemctl daemon-reload
sudo systemctl start sensor-server
sudo systemctl enable sensor-server
sudo systemctl status sensor-server --no-pager

# Step 15: Verify setup
echo -e "${GREEN}Setup complete!${NC}"
echo -e "${GREEN}FastAPI server should be running at http://localhost:$SERVER_PORT${NC}"
echo -e "${GREEN}Cloudflare Tunnel should be accessible at https://$SUBDOMAIN.$DOMAIN${NC}"
echo -e "${GREEN}Check services with:${NC}"
echo "  sudo systemctl status sensor-server"
echo "  sudo systemctl status cloudflared"
echo -e "${GREEN}Test API endpoints:${NC}"
echo "  curl https://$SUBDOMAIN.$DOMAIN/sensors"
echo "  curl https://$SUBDOMAIN.$DOMAIN/health"

deactivate