#!/bin/bash

# Django Backend Startup Script for Mobile Development
echo "🚀 Starting Django Backend for Mobile Development..."

# Navigate to backend directory
cd /var/www/html/personal/small_backend

# Activate virtual environment
source ../env/bin/activate

# Kill any existing Django processes
echo "🔄 Stopping existing Django processes..."
pkill -f "manage.py runserver"
sleep 2

# Get current IP address
IP_ADDRESS=$(hostname -I | awk '{print $1}')
echo "📡 Computer IP Address: $IP_ADDRESS"

# Start Django on all network interfaces
echo "🌐 Starting Django on 0.0.0.0:8000..."
echo "🔗 Backend will be accessible at: http://$IP_ADDRESS:8000"
echo "📱 Mobile app should connect to: http://$IP_ADDRESS:8000"
echo ""
echo "Press Ctrl+C to stop the server"
echo "=================================="

python manage.py runserver 0.0.0.0:8000
