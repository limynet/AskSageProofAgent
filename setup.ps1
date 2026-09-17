# AskSage Proof Agent - Setup Script (PowerShell)
# Run this in PowerShell to install dependencies and start the application

Write-Host "🚀 AskSage Proof Agent Setup" -ForegroundColor Green
Write-Host "============================" -ForegroundColor Green
Write-Host ""

# Check Python installation
Write-Host "📋 Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python not found. Please install Python 3.11+ first." -ForegroundColor Red
    Write-Host "Download from: https://www.python.org/downloads/" -ForegroundColor Cyan
    exit 1
}

# Install Python dependencies
Write-Host ""
Write-Host "📦 Installing Python dependencies..." -ForegroundColor Yellow
try {
    pip install -r requirements.txt
    Write-Host "✅ Dependencies installed successfully" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
    Write-Host "Try running: pip install -r requirements.txt" -ForegroundColor Cyan
    exit 1
}

# Create data directories
Write-Host ""
Write-Host "📁 Creating data directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "data" | Out-Null
New-Item -ItemType Directory -Force -Path "models" | Out-Null
Write-Host "✅ Directories created" -ForegroundColor Green

# Copy .env if it doesn't exist
Write-Host ""
Write-Host "⚙️ Checking configuration..." -ForegroundColor Yellow
if (!(Test-Path ".env")) {
    Copy-Item "configs/.env" -Destination ".env"
    Write-Host "✅ .env file created" -ForegroundColor Green
    Write-Host "⚠️  Edit .env to add your ASKSAGE_API_KEY if needed" -ForegroundColor Yellow
} else {
    Write-Host "✅ .env file already exists" -ForegroundColor Green
}

# Check Docker
Write-Host ""
Write-Host "🐳 Checking Docker..." -ForegroundColor Yellow
try {
    docker version | Out-Null
    Write-Host "✅ Docker is running" -ForegroundColor Green
} catch {
    Write-Host "❌ Docker is not running. Please start Docker Desktop." -ForegroundColor Red
    Write-Host "After starting Docker, run: docker-compose up -d" -ForegroundColor Cyan
    exit 1
}

# Build and start containers
Write-Host ""
Write-Host "🔨 Building and starting containers..." -ForegroundColor Yellow
try {
    docker-compose up -d --build
    Write-Host "✅ Containers started successfully" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to start containers" -ForegroundColor Red
    Write-Host "Check Docker logs: docker-compose logs" -ForegroundColor Cyan
    exit 1
}

# Wait for services to be ready
Write-Host ""
Write-Host "⏳ Waiting for services to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 15

# Check service status
Write-Host ""
Write-Host "📊 Service Status:" -ForegroundColor Yellow
docker-compose ps

# Test Bonsai service
Write-Host ""
Write-Host "🔍 Testing Bonsai LLM service..." -ForegroundColor Yellow
try {
    $response = curl -s http://localhost:11434/api/tags
    if ($response) {
        Write-Host "✅ Bonsai LLM service is accessible" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Bonsai LLM service not responding yet (model may need to be downloaded)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠️  Bonsai LLM service not ready" -ForegroundColor Yellow
    Write-Host "You may need to pull the model: docker exec -it bonsai-llm ollama pull bonsai-1.7b" -ForegroundColor Cyan
}

# Test Streamlit app
Write-Host ""
Write-Host "🔍 Testing Streamlit app..." -ForegroundColor Yellow
try {
    $response = curl -s http://localhost:8501/_stcore/health
    if ($response) {
        Write-Host "✅ Streamlit app is accessible" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Streamlit app not responding yet" -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠️  Streamlit app not ready" -ForegroundColor Yellow
}

# Instructions
Write-Host ""
Write-Host "🎉 Setup Complete!" -ForegroundColor Green
Write-Host "================" -ForegroundColor Green
Write-Host ""
Write-Host "📱 Open your browser to: http://localhost:8501" -ForegroundColor Cyan
Write-Host ""
Write-Host "📝 Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Open http://localhost:8501" -ForegroundColor White
Write-Host "  2. Click '🔍 Test Connection' to verify Bonsai" -ForegroundColor White
Write-Host "  3. Upload a document for review" -ForegroundColor White
Write-Host ""
Write-Host "🛠️  Useful Commands:" -ForegroundColor Yellow
Write-Host "  View logs: docker-compose logs -f" -ForegroundColor White
Write-Host "  Stop: docker-compose down" -ForegroundColor White
Write-Host "  Restart: docker-compose restart" -ForegroundColor White
Write-Host ""