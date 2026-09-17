# ARCHITECTURE.md - AskSageProofAgent Local System Design

## System Overview

AskSageProofAgent Local is a two-container Docker system that transforms manuscript review from cloud-based Ask Sage platform to local inference using Bonsai 1.7B model.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER LAYER                              │
│                                                                 │
│  ┌───────────────┐      ┌───────────────┐      ┌─────────────┐ │
│  │   Boss's      │      │   Nai's       │      │   Testing   │ │
│  │  Browser      │      │  Development  │      │   Scripts   │ │
│  └───────┬───────┘      └───────┬───────┘      └─────┬───────┘ │
│          │                      │                      │         │
│          └──────────────────────┴──────────────────────┘         │
│                           │                                      │
│                  http://localhost:8501                          │
└───────────────────────────┼──────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CONTAINER 2: STREAMLIT APP                    │
│                  Port: 8501 (User Interface)                    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    app.py (UI Layer)                     │  │
│  │  - File upload (PDF/DOCX/TXT)                            │  │
│  │  - Configuration sidebar                                 │  │
│  │  - Review control buttons                                │  │
│  │  - Results display                                       │  │
│  └───────────────┬──────────────────────────────────────────┘  │
│                  │                                               │
│  ┌───────────────▼──────────────────────────────────────────┐  │
│  │               src/ (Business Logic)                       │  │
│  │                                                           │  │
│  │  ┌────────────────┐  ┌────────────────┐                  │  │
│  │  │document_parser │  │  llm_client    │                  │  │
│  │  │    .py         │  │    .py         │                  │  │
│  │  │                │  │                │                  │  │
│  │  │ - PDF extract  │  │ - OpenAI API   │                  │  │
│  │  │ - DOCX extract │  │ - Bonsai 1.7B  │                  │  │
│  │  │ - TXT support  │  │ - asksage.ai fallback│                  │  │
│  │  └────────────────┘  └────────┬───────┘                  │  │
│  │                             │                             │  │
│  │  ┌──────────────────────────▼────────────────────┐       │  │
│  │  │          review_agents.py                      │       │  │
│  │  │                                                  │       │  │
│  │  │  ┌──────────────┐  ┌──────────────┐           │       │  │
│  │  │  │Citation      │  │APA Style     │           │       │  │
│  │  │  │Review Agent  │  │Check Agent   │           │       │  │
│  │  │  │(APA 7th Ed)  │  │(ARI Manual)  │           │       │  │
│  │  │  └──────────────┘  └──────────────┘           │       │  │
│  │  │                                                  │       │  │
│  │  │  ┌──────────────┐  ┌──────────────┐           │       │  │
│  │  │  │Content/SME   │  │Result        │           │       │  │
│  │  │  │Agent         │  │Formatter     │           │       │  │
│  │  │  │(Military)    │  │(Tables, Docs)│           │       │  │
│  │  │  └──────────────┘  └──────────────┘           │       │  │
│  │  └──────────────────────────────────────────────┘       │  │
│  └───────────────────┬───────────────────────────────────────┘  │
│                      │                                            │
└──────────────────────┼────────────────────────────────────────────┘
                       │
                       │ HTTP POST /v1/chat/completions
                       │ OpenAI-compatible API
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                CONTAINER 1: BONSAI 1.7B LLM SERVICE             │
│                  Port: 11434 (Inference API)                    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              llama-cpp-python Server                      │  │
│  │                                                           │  │
│  │  Endpoints:                                               │  │
│  │  - GET  /v1/models           (Model info)                │  │
│  │  - POST /v1/chat/completions (Inference)                 │  │
│  │  - GET  /health               (Health check)             │  │
│  └───────────────┬──────────────────────────────────────────┘  │
│                  │                                               │
│  ┌───────────────▼──────────────────────────────────────────┐  │
│  │              Bonsai 1.7B Model                            │  │
│  │                                                           │  │
│  │  - Quantized: 1-bit (extremely lightweight)              │  │
│  │  - Size: ~2.5 GB (GGUF format)                           │  │
│  │  - Context: 8K tokens                                    │  │
│  │  - Inference: CPU-only                                   │  │
│  │  - Format: GGUF (llama.cpp compatible)                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────┐
│                    FALLBACK LAYER (Optional)                     │
│                                                                   │
│           https://api.asksage.ai/api/coding/paas/v4                   │
│                 Model: gpt-5.1-gov                               │
│                                                                   │
│  Used when Bonsai service is unavailable or for complex tasks   │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Manuscript Upload Flow

```
User uploads PDF
    ↓
Streamlit app receives file
    ↓
document_parser.py extracts text
    ↓
Extracted text stored in memory
    ↓
User clicks "Start Review"
    ↓
Review agents process text sequentially
    ↓
Results formatted as tables
    ↓
Results displayed in UI
```

### 2. Citation Review Flow

```
Citation Review Agent invoked
    ↓
Build prompt (manuscript + ARI Manual)
    ↓
llm_client.py calls Bonsai API
    ↓
Bonsai generates review response
    ↓
Response parsed into table format
    ↓
Table displayed in Streamlit UI
    ↓
Downloadable report generated
```

### 3. Fallback Mechanism

```
llm_client.py attempts Bonsai
    ↓
Bonsai API call fails (timeout/error)
    ↓
Automatic fallback to asksage.ai
    ↓
asksage.ai API called with same prompt
    ↓
Response returned to app
    ↓
Warning logged: "Fallback to asksage.ai activated"
```

## Container Communication

### Network Architecture

```
docker-compose.yml creates network: ask-sage-network

Container 1 (bonsai-llm):
  - Hostname: bonsai-llm
  - Port mapping: 11434:11434
  - Accessible from host: localhost:11434
  - Accessible from Container 2: http://bonsai-llm:11434

Container 2 (streamlit-app):
  - Hostname: ask-sage-local
  - Port mapping: 8501:8501
  - Accessible from host: localhost:8501
  - Accesses Container 1: http://bonsai-llm:11434

Host machine:
  - Access Bonsai: localhost:11434
  - Access Streamlit: localhost:8501
```

### API Communication

```
Container 2 → Container 1:
  POST http://bonsai-llm:11434/v1/chat/completions
  Headers: Content-Type: application/json
  Body: {
    "model": "bonsai-1.7b",
    "messages": [...],
    "temperature": 0.2,
    "max_tokens": 2000
  }

Container 1 → Container 2:
  Response: {
    "id": "chat-123",
    "object": "chat.completion",
    "created": 1234567890,
    "model": "bonsai-1.7b",
    "choices": [{
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Review results..."
      },
      "finish_reason": "stop"
    }]
  }
```

## Storage Architecture

### Volume Mounts

```
Container 1 (bonsai-llm):
  - ./models:/models (Read-only)
    - bonsai-1.7b.gguf (Model weights)
    - tokenizer.json (Tokenization config)

Container 2 (streamlit-app):
  - ./data:/app/data (Read-write)
    - uploads/ (Uploaded manuscripts)
    - results/ (Generated reviews)
    - cache/ (Temporary files)

  - ./configs:/app/configs (Read-only)
    - .env (Configuration)
```

### File Lifecycle

```
1. User uploads manuscript.pdf
   ↓
2. Saved to ./data/uploads/manuscript.pdf
   ↓
3. Parsed to text in memory
   ↓
4. Sent to Bonsai for inference
   ↓
5. Results saved to ./data/results/review_YYYYMMDD_HHMMSS.json
   ↓
6. Displayed in UI
   ↓
7. User downloads report
   ↓
8. Files retained for 7 days (cleanup policy)
```

## Security Architecture

### API Keys

```
Bonsai (local):
  - No API key required
  - Access restricted to Docker network
  - Not exposed to host machine

asksage.ai (cloud fallback):
  - API key stored in .env
  - Loaded as environment variable
  - Not committed to git
  - Used only when Bonsai unavailable
```

### Network Security

```
Port exposure:
  - 8501: Streamlit UI (User access)
  - 11434: Bonsai API (Internal only)

Firewall rules:
  - Allow localhost → 8501 (User access)
  - Allow localhost → 11434 (Testing only)
  - Allow Container 2 → Container 1 (Internal)
  - Block external → 11434 (Security)
```

## Performance Considerations

### Bonsai 1.7B Performance

```
Model specifications:
  - Parameters: 1.7B
  - Quantization: 1-bit
  - Size: 2.5 GB
  - RAM required: 4 GB min
  - Inference speed: ~5-10 tokens/second (CPU)

Expected performance:
  - Short queries (500 tokens): ~50-100 seconds
  - Medium queries (2000 tokens): ~200-400 seconds
  - Long queries (8000 tokens): ~800-1600 seconds
```

### Optimization Strategies

```
1. Prompt engineering:
   - Keep prompts concise
   - Use structured templates
   - Minimize context window usage

2. Caching:
   - Cache repeated queries
   - Cache model loading
   - Cache parsed documents

3. Parallel processing:
   - Multiple review agents run sequentially (Phase 1)
   - Consider parallel agents (Phase 3)

4. Resource management:
   - Monitor memory usage
   - Implement rate limiting
   - Graceful degradation
```

## Scalability Path

### Current (Phase 1)

```
1 Bonsai container (CPU)
  ├─ 1 instance
  ├─ ~4 GB RAM
  └─ Sequential processing
```

### Future (Phase 3)

```
Multiple Bonsai containers (GPU)
  ├─ Multiple instances (load balanced)
  ├─ GPU acceleration
  └─ Parallel processing

or

Foundry PLTR platform
  ├─ Unlimited LLM API
  ├─ Auto-scaling
  └─ Production deployment
```

## Monitoring & Observability

### Health Checks

```
Container 1 (Bonsai):
  - Endpoint: /health
  - Check every 30s
  - Timeout: 10s
  - Retries: 3

Container 2 (Streamlit):
  - Endpoint: http://localhost:8501/_stcore/health
  - Check every 30s
  - Timeout: 10s
  - Retries: 3
```

### Logging

```
Application logs (Streamlit):
  - File: ./data/logs/app.log
  - Rotation: Daily
  - Retention: 30 days

LLM service logs (Bonsai):
  - File: ./data/logs/bonsai.log
  - Rotation: Daily
  - Retention: 30 days

Error logs:
  - Separate file for errors
  - Alerting configured
  - Immediate notification
```

### Metrics

```
Key metrics to track:
  - Request count per hour
  - Average response time
  - Error rate
  - Memory usage
  - CPU utilization
  - Token consumption

Visualization:
  - Streamlit metrics dashboard
  - Docker stats monitoring
  - Optional: Prometheus/Grafana
```

## Disaster Recovery

### Backup Strategy

```
Daily backups:
  - ./data/ directory
  - ./configs/ directory
  - Backup location: E:/Backup/AskSageProofAgent_Local/

Retention policy:
  - Daily backups: 7 days
  - Weekly backups: 4 weeks
  - Monthly backups: 3 months
```

### Recovery Procedures

```
Container crash:
  1. Docker auto-restarts (unless-stopped policy)
  2. Health check validates recovery
  3. System operational in < 5 minutes

Data corruption:
  1. Stop containers
  2. Restore from backup
  3. Restart containers
  4. Verify data integrity

Network failure:
  1. Bonsai unavailable (local, unlikely)
  2. Auto-fallback to asksage.ai
  3. Warning logged
  4. Continue operation
```

