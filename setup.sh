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
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting setup for FastAPI server and Cloudflare Tunnel...${NC}"

# Step 1: Update system and install dependencies
echo -e "${GREEN}Installing system dependencies...${NC}"
sudo apt update
sudo apt install -y python3 python3-pip python3-venv wget curl

# Step 2: Create working directory
echo -e "${GREEN}Setting up working directory at $WORKDIR...${NC}"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

# Step 3: Create requirements.txt if it doesn't exist
echo -e "${GREEN}Creating requirements.txt...${NC}"
cat > requirements.txt << 'EOL'
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
RPi.GPIO==0.7.1
Adafruit-DHT==1.4.0
spidev==3.6
python-multipart==0.0.6
EOL

# Step 4: Copy server.py if it exists, otherwise create a basic one
if [ ! -f "server.py" ]; then
    echo -e "${YELLOW}server.py not found. You'll need to add your FastAPI server code to $WORKDIR/server.py${NC}"
    echo -e "${YELLOW}Please copy your server.py file to this location before continuing.${NC}"
    read -p "Press Enter to continue once you've added server.py..." -r
fi

# Step 5: Create and activate virtual environment
echo -e "${GREEN}Creating Python virtual environment...${NC}"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Step 6: Install Python dependencies
echo -e "${GREEN}Installing Python packages from requirements.txt...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# Step 7: Install cloudflared
echo -e "${GREEN}Installing cloudflared...${NC}"
ARCH=$(uname -m)
case "$ARCH" in
    "aarch64")
        CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
        ;;
    "armv7l"|"armv6l")
        CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm"
        ;;
    "x86_64")
        CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
        ;;
    *)
        echo -e "${RED}Unsupported architecture: $ARCH${NC}"
        exit 1
        ;;
esac

wget "$CLOUDFLARED_URL" -O cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/cloudflared

# Verify cloudflared installation
echo -e "${GREEN}Cloudflared version:${NC}"
cloudflared --version

# Step 8: Authenticate with Cloudflare
echo -e "${GREEN}Authenticating with Cloudflare...${NC}"
echo -e "${YELLOW}A browser window will open. Please log in to your Cloudflare account and authorize the tunnel.${NC}"
mkdir -p "$CONFIG_DIR"
cloudflared tunnel login

# Verify authentication
if [ ! -f "$CONFIG_DIR/cert.pem" ]; then
    echo -e "${RED}Error: Cloudflare authentication failed, cert.pem not found!${NC}"
    echo -e "${YELLOW}Please run 'cloudflared tunnel login' manually and try again.${NC}"
    exit 1
fi
echo -e "${GREEN}Cloudflare authentication successful!${NC}"

# Step 9: Create Cloudflare Tunnel
echo -e "${GREEN}Creating Cloudflare Tunnel: $TUNNEL_NAME...${NC}"

# Check if tunnel already exists
if cloudflared tunnel list | grep -q "$TUNNEL_NAME"; then
    echo -e "${YELLOW}Tunnel $TUNNEL_NAME already exists. Using existing tunnel.${NC}"
    TUNNEL_ID=$(cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
else
    cloudflared tunnel create "$TUNNEL_NAME"
    TUNNEL_ID=$(cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
fi

if [ -z "$TUNNEL_ID" ]; then
    echo -e "${RED}Error: Failed to retrieve Tunnel ID!${NC}"
    exit 1
fi
echo -e "${GREEN}Tunnel ID: $TUNNEL_ID${NC}"

# Step 10: Create Cloudflare Tunnel configuration
echo -e "${GREEN}Creating Cloudflare Tunnel configuration...${NC}"
cat > "$CONFIG_DIR/config.yml" << EOL
tunnel: $TUNNEL_ID
credentials-file: $CONFIG_DIR/$TUNNEL_ID.json

ingress:
  - hostname: $SUBDOMAIN.$DOMAIN
    service: http://localhost:$SERVER_PORT
    originRequest:
      httpHostHeader: $SUBDOMAIN.$DOMAIN
      noTLSVerify: true
  - service: http_status:404

EOL

# Step 11: Create DNS record
echo -e "${GREEN}Creating DNS record...${NC}"
cloudflared tunnel route dns "$TUNNEL_ID" "$SUBDOMAIN.$DOMAIN"

# Verify DNS record creation
echo -e "${GREEN}DNS record created for $SUBDOMAIN.$DOMAIN pointing to $TUNNEL_ID.cfargotunnel.com${NC}"

# Step 12: Test tunnel configuration
echo -e "${GREEN}Testing tunnel configuration...${NC}"
if cloudflared tunnel --config "$CONFIG_DIR/config.yml" ingress validate; then
    echo -e "${GREEN}Tunnel configuration is valid!${NC}"
else
    echo -e "${RED}Tunnel configuration validation failed!${NC}"
    exit 1
fi

# Step 13: Install cloudflared as a system service
echo -e "${GREEN}Installing cloudflared as a system service...${NC}"
sudo cloudflared service install --config "$CONFIG_DIR/config.yml"

# Step 14: Start and enable cloudflared service
echo -e "${GREEN}Starting cloudflared service...${NC}"
sudo systemctl start cloudflared
sudo systemctl enable cloudflared

# Wait a moment for the service to start
sleep 5
sudo systemctl status cloudflared --no-pager

# Step 15: Create systemd service for FastAPI server
echo -e "${GREEN}Creating systemd service for FastAPI server...${NC}"
sudo bash -c "cat > /etc/systemd/system/sensor-server.service" << EOL
[Unit]
Description=FastAPI Sensor Server
After=network.target
Wants=cloudflared.service

[Service]
Type=simple
User=$PI_USER
Group=$PI_USER
WorkingDirectory=$WORKDIR
Environment="PATH=$VENV_DIR/bin"
Environment="PYTHONPATH=$WORKDIR"
ExecStart=$VENV_DIR/bin/uvicorn server:app --host 0.0.0.0 --port $SERVER_PORT --reload
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# Step 16: Start and enable FastAPI server service
echo -e "${GREEN}Starting FastAPI server service...${NC}"
sudo systemctl daemon-reload
sudo systemctl start sensor-server
sudo systemctl enable sensor-server

# Wait a moment for the service to start
sleep 5
sudo systemctl status sensor-server --no-pager

# Step 17: Final verification
echo -e "${GREEN}Running final verification...${NC}"

# Test local server
echo -e "${GREEN}Testing local server...${NC}"
if curl -s http://localhost:$SERVER_PORT/health > /dev/null; then
    echo -e "${GREEN}✓ Local server is responding${NC}"
else
    echo -e "${RED}✗ Local server is not responding${NC}"
fi

# Test tunnel
echo -e "${GREEN}Testing Cloudflare tunnel...${NC}"
sleep 10  # Give tunnel time to establish
if curl -s -H "User-Agent: Setup-Script/1.0" https://$SUBDOMAIN.$DOMAIN/health > /dev/null; then
    echo -e "${GREEN}✓ Cloudflare tunnel is working${NC}"
else
    echo -e "${YELLOW}⚠ Cloudflare tunnel may still be connecting. This can take a few minutes.${NC}"
fi

# Step 18: Setup complete
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Setup complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${GREEN}Local Access:${NC}"
echo "  FastAPI server: http://localhost:$SERVER_PORT"
echo "  API docs: http://localhost:$SERVER_PORT/docs"
echo ""
echo -e "${GREEN}Public Access:${NC}"
echo "  Your API: https://$SUBDOMAIN.$DOMAIN"
echo "  API docs: https://$SUBDOMAIN.$DOMAIN/docs"
echo ""
echo -e "${GREEN}Service Management:${NC}"
echo "  Check sensor server: sudo systemctl status sensor-server"
echo "  Check cloudflare tunnel: sudo systemctl status cloudflared"
echo "  Restart sensor server: sudo systemctl restart sensor-server"
echo "  Restart tunnel: sudo systemctl restart cloudflared"
echo "  View logs: sudo journalctl -u sensor-server -f"
echo "  View tunnel logs: sudo journalctl -u cloudflared -f"
echo ""
echo -e "${GREEN}Test Commands:${NC}"
echo "  curl https://$SUBDOMAIN.$DOMAIN/health"
echo "  curl https://$SUBDOMAIN.$DOMAIN/sensors"
echo "  curl https://$SUBDOMAIN.$DOMAIN/config"
echo ""
echo -e "${GREEN}Cloudflare Dashboard:${NC}"
echo "  Check your tunnel status at: https://dash.cloudflare.com/"
echo ""
echo -e "${YELLOW}Note: It may take a few minutes for the tunnel to fully establish.${NC}"
echo -e "${YELLOW}If you encounter issues, check the service logs using the commands above.${NC}"

deactivate