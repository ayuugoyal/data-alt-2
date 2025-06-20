#!/bin/bash

# Configuration variables
PI_USER="dataalt"
WORKDIR="/home/$PI_USER/sensor-server"
VENV_DIR="$WORKDIR/venv"
SERVER_PORT=8000
DOMAIN="datalyticx.com"
SUBDOMAIN="sensors"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Completing FastAPI service setup...${NC}"

# Check if cloudflared service is running
echo -e "${GREEN}Checking cloudflared service status...${NC}"
sudo systemctl status cloudflared --no-pager

# Create systemd service for FastAPI server
echo -e "${GREEN}Creating systemd service for FastAPI server...${NC}"
sudo tee /etc/systemd/system/sensor-server.service > /dev/null <<EOF
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
EOF

# Reload systemd and start services
echo -e "${GREEN}Starting FastAPI server service...${NC}"
sudo systemctl daemon-reload
sudo systemctl start sensor-server
sudo systemctl enable sensor-server

# Wait a moment for the service to start
sleep 5

# Check service status
echo -e "${GREEN}Checking service statuses...${NC}"
echo -e "${YELLOW}FastAPI Server Status:${NC}"
sudo systemctl status sensor-server --no-pager

echo ""
echo -e "${YELLOW}Cloudflared Tunnel Status:${NC}"
sudo systemctl status cloudflared --no-pager

# Test local server
echo -e "${GREEN}Testing local server...${NC}"
sleep 3
if curl -s http://localhost:$SERVER_PORT/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Local server is responding${NC}"
else
    echo -e "${YELLOW}⚠ Local server test - checking if server is starting...${NC}"
    # Try to get some response even if /health endpoint doesn't exist
    if curl -s http://localhost:$SERVER_PORT/ > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Local server is responding (no /health endpoint)${NC}"
    else
        echo -e "${RED}✗ Local server is not responding${NC}"
        echo -e "${YELLOW}Check logs with: sudo journalctl -u sensor-server -f${NC}"
    fi
fi

# Test tunnel (give it time to establish)
echo -e "${GREEN}Testing Cloudflare tunnel (this may take a moment)...${NC}"
sleep 15
if curl -s -H "User-Agent: Setup-Script/1.0" https://$SUBDOMAIN.$DOMAIN/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Cloudflare tunnel is working${NC}"
elif curl -s -H "User-Agent: Setup-Script/1.0" https://$SUBDOMAIN.$DOMAIN/ > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Cloudflare tunnel is working (no /health endpoint)${NC}"
else
    echo -e "${YELLOW}⚠ Cloudflare tunnel may still be connecting. This can take a few minutes.${NC}"
    echo -e "${YELLOW}Check tunnel logs with: sudo journalctl -u cloudflared -f${NC}"
fi

# Final summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Setup Summary${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${GREEN}Services Status:${NC}"
echo "  FastAPI Server: $(sudo systemctl is-active sensor-server)"
echo "  Cloudflare Tunnel: $(sudo systemctl is-active cloudflared)"
echo ""
echo -e "${GREEN}Access URLs:${NC}"
echo "  Local: http://localhost:$SERVER_PORT"
echo "  Local API docs: http://localhost:$SERVER_PORT/docs"
echo "  Public: https://$SUBDOMAIN.$DOMAIN"
echo "  Public API docs: https://$SUBDOMAIN.$DOMAIN/docs"
echo ""
echo -e "${GREEN}Useful Commands:${NC}"
echo "  Check FastAPI logs: sudo journalctl -u sensor-server -f"
echo "  Check tunnel logs: sudo journalctl -u cloudflared -f"
echo "  Restart FastAPI: sudo systemctl restart sensor-server"
echo "  Restart tunnel: sudo systemctl restart cloudflared"
echo "  Test local: curl http://localhost:$SERVER_PORT/"
echo "  Test public: curl https://$SUBDOMAIN.$DOMAIN/"
echo ""
echo -e "${YELLOW}Note: If the tunnel test failed, wait a few minutes and try:${NC}"
echo -e "${YELLOW}curl https://$SUBDOMAIN.$DOMAIN/${NC}"