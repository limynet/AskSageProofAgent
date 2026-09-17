#!/bin/bash
# AskSage Proof Agent - Setup Script (Bash/Git-Bash)
# Run this in Git-Bash or terminal to install dependencies and start the application

echo "🚀 AskSage Proof Agent Setup"
echo "============================"
echo ""

# Check Python installation
echo "📋 Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
elif command -v python &> /dev/null; then
    PYTHON_CMD=python
else
    echo "❌ Python not found. Please install Python 3.11+ first."
    echo "Download from: https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)
echo "✅ Python found: $PYTHON_VERSION"

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
if $PYTHON_CMD -m pip install -r requirements.txt; then
    echo "✅ Dependencies installed successfully"
else
    echo "❌ Failed to install dependencies"
    echo "Try running: $PYTHON_CMD -m pip install -r requirements.txt"
    exit 1
fi

# Create data directories
echo ""
echo "📁 Creating data directories..."
mkdir -p data models
echo "✅ Directories created"

# Copy .env if it doesn't exist
echo ""
echo "⚙️ Checking configuration..."
if [ ! -f ".env" ]; then
    cp configs/.env .env
    echo "✅ .env file created"
    echo "⚠️  Edit .env to add your ASKSAGE_API_KEY if needed"
else
    echo "✅ .env file already exists"
fi

# Check Docker
echo ""
echo "🐳 Checking Docker..."
if docker info > /dev/null 2>&1; then
    echo "✅ Docker is running"
else
    echo "❌ Docker is not running. Please start Docker Desktop."
    echo "After starting Docker, run: docker-compose up -d"
    exit 1
fi

# Build and start containers
echo ""
echo "🔨 Building and starting containers..."
if docker-compose up -d --build; then
    echo "✅ Containers started successfully"
else
    echo "❌ Failed to start containers"
    echo "Check Docker logs: docker-compose logs"
    exit 1
fi

# Wait for services to be ready
echo ""
echo "⏳ Waiting for services to start..."
sleep 15

# Check service status
echo ""
echo "📊 Service Status:"
docker-compose ps

# Test Bonsai service
echo ""
echo "🔍 Testing Bonsai LLM service..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✅ Bonsai LLM service is accessible"
else
    echo "⚠️  Bonsai LLM service not responding yet (model may need to be downloaded)"
    echo "You may need to pull the model: docker exec -it bonsai-llm ollama pull bonsai-1.7b"
fi

# Test Streamlit app
echo ""
echo "🔍 Testing Streamlit app..."
if curl -s http://localhost:8501/_stcore/health > /dev/null 2>&1; then
    echo "✅ Streamlit app is accessible"
else
    echo "⚠️  Streamlit app not responding yet"
fi

# Instructions
echo ""
echo "🎉 Setup Complete!"
echo "================"
echo ""
echo "📱 Open your browser to: http://localhost:8501"
echo ""
echo "📝 Next Steps:"
echo "  1. Open http://localhost:8501"
echo "  2. Click '🔍 Test Connection' to verify Bonsai"
echo "  3. Upload a document for review"
echo ""
echo "🛠️  Useful Commands:"
echo "  View logs: docker-compose logs -f"
echo "  Stop: docker-compose down"
echo "  Restart: docker-compose restart"
echo ""