# README.md - AskSageProofAgent Local Development Plan (Research Plan and PRD)

## Project Overview

**Goal**: Transform AskSageProofAgent from Ask Sage cloud platform to local Docker-based system using Bonsai 1.7B model.

**Architecture**: Two-container system
- Container 1: Bonsai 1.7B LLM Service (Local inference)
- Container 2: Streamlit Application Pipeline

**Phase Roadmap**:
- Phase 1: Local Docker Prototype (Current)
- Phase 2: Foundry PLTR Migration (Unlimited LLM API)
- Phase 3: Architecture Enhancement

---

## Phase 1: Local Docker Prototype

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   User Browser                               │
│              http://localhost:8501                           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│           Container 2: Streamlit App                         │
│  - app.py (UI)                                              │
│  - src/llm_client.py (LLM integration)                      │
│  - src/document_parser.py (PDF/DOCX/TXT)                    │
│  - src/review_agents.py (Citation, APA, SME)                │
│  - configs/.env (Configuration)                             │
└────────────────────┬────────────────────────────────────────┘
                     │ OpenAI-compatible API
                     │ http://host.docker.internal:11434
                     ▼
┌─────────────────────────────────────────────────────────────┐
│         Container 1: Bonsai 1.7B LLM Service                 │
│  - Ollama-like API interface                                │
│  - Bonsai 1.7B quantized model                               │
│  - Port: 11434                                              │
└─────────────────────────────────────────────────────────────┘
```

### Task Breakdown

#### Step 1: Bonsai Model Acquisition
**Status**: 🔄 Planning
**Estimated Time**: 15-30 minutes

**Requirements**:
- Download Bonsai 1.7B model files (GGUF quantized format)
- Target location: `models/` directory
- Model size: ~2-3 GB (quantized)

**Approach Options**:
1. **Option A**: Direct download from HuggingFace
   - Repository: prism-ml/bonsai (1-bit quantized)
   - Command: `huggingface-cli download prism-ml/bonsai`

2. **Option B**: Clone Bonsai-demo repo and extract
   - Repo: https://github.com/PrismML-Eng/Bonsai-demo
   - Use provided scripts for model management

3. **Option C**: Use Ollama-style model registry
   - Create local Modelfile
   - Build with `ollama create bonsai-1.7b`

**Decision**: Use Option A (HuggingFace) for direct access to quantized models

---

#### Step 2: Docker Container 1 - Bonsai LLM Service
**Status**: ⏳ Not Started
**Estimated Time**: 30-45 minutes

**Requirements**:
- Docker container running Bonsai 1.7B inference
- Ollama-compatible API endpoint on port 11434
- OpenAI-compatible completion/chat endpoints
- Health check endpoint
- Persistent model storage

**Dockerfile Plan**:
```dockerfile
FROM python:3.11-slim

# Install dependencies
RUN pip install --no-cache-dir \
    llama-cpp-python \
    fastapi \
    uvicorn \
    pydantic

# Copy model files
COPY models/ /models/

# Expose API port
EXPOSE 11434

# Run inference server
CMD ["python", "-m", "llama_cpp.server", \
     "--model", "/models/bonsai-1.7b.gguf", \
     "--host", "0.0.0.0", \
     "--port", "11434", \
     "--chat_format", "openai"]
```

**docker-compose.yml Entry**:
```yaml
bonsai-llm:
  build:
    context: .
    dockerfile: Dockerfile.bonsai
  container_name: bonsai-llm
  ports:
    - "11434:11434"
  volumes:
    - ./models:/models
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:11434/health"]
    interval: 30s
    timeout: 10s
    retries: 3
```

**Verification Tests**:
- [ ] Container starts successfully
- [ ] Port 11434 is accessible from host
- [ ] `/v1/models` endpoint returns Bonsai 1.7B
- [ ] `/v1/chat/completions` endpoint works
- [ ] Health check passes
- [ ] Test inference with simple prompt

---

#### Step 3: Test Bonsai LLM Service
**Status**: ⏳ Not Started
**Estimated Time**: 15 minutes

**Test Plan**:
1. Basic connectivity test
   ```bash
   curl http://localhost:11434/v1/models
   ```

2. Simple inference test
   ```bash
   curl -X POST http://localhost:11434/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "bonsai-1.7b",
       "messages": [{"role": "user", "content": "Say hello"}],
       "max_tokens": 50
     }'
   ```

3. Citation review test (mini version)
   - Use extracted manuscript text
   - Test citation analysis prompt
   - Verify response format

4. Performance benchmark
   - Measure response time for 1K tokens
   - Check memory usage
   - Monitor CPU utilization

**Success Criteria**:
- [ ] All API endpoints respond correctly
- [ ] Response time < 10 seconds for typical queries
- [ ] JSON output matches OpenAI format
- [ ] No memory leaks or crashes

---

#### Step 4: Docker Container 2 - Streamlit Application
**Status**: 🔄 In Progress (Basic UI deployed)
**Estimated Time**: 45-60 minutes

**Requirements**:
- Streamlit app with file upload
- LLM client integration (support both Bonsai and asksage.ai)
- Document parsing (PDF/DOCX/TXT)
- Review agents (Citations, APA, SME)
- Config management
- Health monitoring

**Dockerfile Plan**:
```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY src/ ./src/
COPY configs/ ./configs/

# Create data directory
RUN mkdir -p /app/data

# Expose Streamlit port
EXPOSE 8501

# Set environment variables
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Run Streamlit
CMD ["streamlit", "run", "app.py"]
```

**docker-compose.yml Entry**:
```yaml
streamlit-app:
  build:
    context: .
    dockerfile: Dockerfile.app
  container_name: ask-sage-local
  ports:
    - "8501:8501"
  volumes:
    - ./data:/app/data
    - ./configs:/app/configs
  environment:
    - ACTIVE_MODEL=bonsai
    - BONSAI_API_BASE=http://bonsai-llm:11434/v1
  depends_on:
    - bonsai-llm
  restart: unless-stopped
```

---

#### Step 5: LLM Client Module Implementation
**Status**: ⏳ Not Started
**Estimated Time**: 30 minutes

**Requirements**:
- OpenAI-compatible API client
- Support for Bonsai (primary) and asksage.ai (fallback)
- Error handling and retry logic
- Token counting and rate limiting
- Response parsing and validation

**Implementation Plan**:
```python
# src/llm_client.py
from openai import OpenAI
import os
from dotenv import load_dotenv

class LLMClient:
    def __init__(self, model_type="bonsai"):
        load_dotenv()
        self.model_type = model_type
        self.setup_client()

    def setup_client(self):
        if self.model_type == "bonsai":
            self.client = OpenAI(
                base_url=os.getenv("BONSAI_API_BASE"),
                api_key=os.getenv("BONSAI_API_KEY")
            )
            self.model = os.getenv("BONSAI_MODEL")
        else:
            self.client = OpenAI(
                base_url=os.getenv("ZAI_API_BASE"),
                api_key=os.getenv("ZAI_API_KEY")
            )
            self.model = os.getenv("ZAI_MODEL")

    def chat_completion(self, messages, temperature=0.1, max_tokens=2000):
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            # Fallback to asksage.ai if Bonsai fails
            if self.model_type == "bonsai":
                self.model_type = "asksage"
                self.setup_client()
                return self.chat_completion(messages, temperature, max_tokens)
            raise```
```

---

#### Step 6: Document Parser Module
**Status**: ⏳ Not Started
**Estimated Time**: 45 minutes

**Requirements**:
- PDF text extraction (PyPDF2)
- DOCX text extraction (python-docx)
- TXT file support
- Page number tracking
- Metadata extraction

**Implementation Plan**:
```python
# src/document_parser.py
import PyPDF2
from docx import Document
from pathlib import Path

class DocumentParser:
    def parse(self, file_path):
        ext = Path(file_path).suffix.lower()

        if ext == '.pdf':
            return self.parse_pdf(file_path)
        elif ext == '.docx':
            return self.parse_docx(file_path)
        elif ext == '.txt':
            return self.parse_txt(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    def parse_pdf(self, file_path):
        reader = PyPDF2.PdfReader(file_path)
        text = ""
        for page_num, page in enumerate(reader.pages):
            text += f"\n--- Page {page_num + 1} ---\n"
            text += page.extract_text()
        return text

    def parse_docx(self, file_path):
        doc = Document(file_path)
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text

    def parse_txt(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
```

---

#### Step 7: Review Agents Module
**Status**: ⏳ Not Started
**Estimated Time**: 60-90 minutes

**Requirements**:
- Citation Review Agent (APA 7th Edition + ARI Manual)
- APA Style Check Agent
- Content/SME Agent
- Use Bonsai 1.7B for inference
- Table-formatted output
- Summary letter generation

**Implementation Plan** (based on JSON configs):
```python
# src/review_agents.py
from .llm_client import LLMClient

class CitationReviewAgent:
    def __init__(self, llm_client):
        self.llm_client = llm_client

    def review(self, manuscript_text, ari_manual_text):
        prompt = self._build_citation_prompt(manuscript_text, ari_manual_text)

        messages = [
            {"role": "system", "content": "You are an expert APA 7th Edition citation reviewer..."},
            {"role": "user", "content": prompt}
        ]

        response = self.llm_client.chat_completion(
            messages=messages,
            temperature=0.2,
            max_tokens=2000
        )

        return self._parse_citation_table(response)

    def _build_citation_prompt(self, manuscript, ari_manual):
        return f"""
You are an expert APA 7th Edition and ARI Publication Manual citation reviewer.

## MANUSCRIPT
{manuscript}

## ARI PUBLICATION MANUAL
{ari_manual}

## TASK
Generate a comprehensive review of citations and references.

Table format:
| Page Number | Original Text | Issue Identified/Reason | Correct Response/Updated Text | APA/ARI Source Link |

Provide the table followed by a summary.
"""

class APAStyleAgent:
    def __init__(self, llm_client):
        self.llm_client = llm_client

    def review(self, manuscript_text):
        prompt = self._build_apa_prompt(manuscript_text)
        # Similar implementation
        pass

class ContentSMEAgent:
    def __init__(self, llm_client):
        self.llm_client = llm_client

    def review(self, manuscript_text, army_docs):
        prompt = self._build_sme_prompt(manuscript_text, army_docs)
        # Similar implementation
        pass
```

---

#### Step 8: Integration Testing
**Status**: ⏳ Not Started
**Estimated Time**: 45 minutes

**Test Cases**:
1. End-to-end workflow test
   - Upload PDF manuscript
   - Extract content
   - Run citation review
   - Run APA check
   - Display results

2. Model fallback test
   - Intentionally break Bonsai service
   - Verify fallback to asksage.ai works
   - Restore Bonsai
   - Verify switch back

3. Large file handling
   - Upload 50+ page manuscript
   - Monitor memory usage
   - Verify performance

4. Concurrent user simulation
   - Multiple simultaneous uploads
   - Verify no crashes
   - Check response times

**Success Criteria**:
- [ ] Complete workflow runs without errors
- [ ] Results display correctly in Streamlit UI
- [ ] Fallback mechanism works
- [ ] Performance acceptable (<30s per review)

---

#### Step 9: Docker Compose Orchestration
**Status**: ⏳ Not Started
**Estimated Time**: 20 minutes

**Complete docker-compose.yml**:
```yaml
version: '3.8'

services:
  # Bonsai 1.7B LLM Service
  bonsai-llm:
    build:
      context: .
      dockerfile: Dockerfile.bonsai
    container_name: bonsai-llm
    ports:
      - "11434:11434"
    volumes:
      - ./models:/models
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - ask-sage-network

  # Streamlit Application
  streamlit-app:
    build:
      context: .
      dockerfile: Dockerfile.app
    container_name: ask-sage-local
    ports:
      - "8501:8501"
    volumes:
      - ./data:/app/data
      - ./configs:/app/configs
    environment:
      - ACTIVE_MODEL=bonsai
      - BONSAI_API_BASE=http://bonsai-llm:11434/v1
      - BONSAI_API_KEY=not-needed-for-local
      - BONSAI_MODEL=bonsai-1.7b
    depends_on:
      bonsai-llm:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - ask-sage-network

networks:
  ask-sage-network:
    driver: bridge

volumes:
  models:
  data:
```

---

#### Step 10: Documentation & Launch Script
**Status**: ⏳ Not Started
**Estimated Time**: 30 minutes

**Deliverables**:
1. `run_docker.sh` - One-click launch script
2. `stop_docker.sh` - Shutdown script
3. `test_docker.sh` - Automated test script
4. Updated `README.md` with Docker instructions
5. `Docker_setup_guide.md` - Detailed setup guide

**Launch Script Plan**:
```bash
#!/bin/bash
# run_docker.sh

echo "Starting AskSageProofAgent Local..."

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "Error: Docker not installed"
    exit 1
fi

# Check docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo "Error: docker-compose not installed"
    exit 1
fi

# Build and start containers
echo "Building Docker images..."
docker-compose build

echo "Starting containers..."
docker-compose up -d

# Wait for services
echo "Waiting for services to start..."
sleep 10

# Check health
echo "Checking service health..."
curl -f http://localhost:11434/health || echo "Bonsai LLM service not ready"
curl -f http://localhost:8501 || echo "Streamlit app not ready"

echo "✅ System ready!"
echo "Access the application at: http://localhost:8501"
```

---

## Configuration Details

### Environment Variables (.env)
```bash
# Local Bonsai Model (Primary)
BONSAI_API_BASE=http://bonsai-llm:11434/v1
BONSAI_API_KEY=not-needed-for-local
BONSAI_MODEL=bonsai-1.7b

# Fallback to Ask Sage model (same as JSON configs)
AI_API_BASE=https://api.asksage.ai/api/coding/paas/v4
AI_API_KEY=your_api_key_here
AI_MODEL=gpt-5.1-gov

# Active model: use 'bonsai' or 'asksage'
ACTIVE_MODEL=bonsai
```

### Model Requirements
- **Primary**: Bonsai 1.7B (quantized, 1-bit)
  - Size: ~2.5 GB
  - RAM: 4 GB minimum
  - Inference: CPU-only
- **Fallback**: gpt-5.1-gov (asksage.ai)
  - Same model as original Ask Sage JSON configs
  - Used when local service unavailable

---

## Testing & Validation

### Unit Tests
- [ ] Document parser tests (PDF, DOCX, TXT)
- [ ] LLM client tests (both models)
- [ ] Review agent tests (prompt engineering)

### Integration Tests
- [ ] End-to-end workflow
- [ ] Model fallback mechanism
- [ ] Docker container health
- [ ] API endpoint responses

### Performance Tests
- [ ] Response time benchmark
- [ ] Memory usage monitoring
- [ ] Concurrent user simulation

### User Acceptance Tests
- [ ] Boss can upload files
- [ ] Boss can run reviews
- [ ] Results display clearly
- [ ] No technical setup required

---

## Known Limitations & Mitigations

### Limitations
1. **Model Capacity**: Bonsai 1.7B is smaller than gpt-5.1-gov
   - Mitigation: Fallback to asksage.ai for complex tasks

2. **CPU Inference**: No GPU acceleration
   - Mitigation: Use quantized model, optimize prompts

3. **Context Window**: Limited context length
   - Mitigation: Chunk large documents, process sections

4. **Accuracy**: Smaller model may be less accurate
   - Mitigation: Human review still required

### Future Enhancements
1. GPU acceleration (if hardware available)
2. Larger Bonsai model (8B, 27B)
3. Distributed inference
4. Caching mechanism for repeated queries

---

## Progress Tracking

### Completed
- [x] Phase 1 planning and architecture design
- [x] Project directory structure created
- [x] Basic Streamlit UI deployed (localhost:8501)
- [x] Dependencies installed

### In Progress
- [ ] Bonsai 1.7B model acquisition
- [ ] Docker container 1 (LLM service) setup
- [ ] Docker container 2 (Streamlit app) setup

### Not Started
- [ ] LLM client module implementation
- [ ] Document parser module implementation
- [ ] Review agents module implementation
- [ ] Integration testing
- [ ] Documentation completion

---

## Commit Log

### 2026-07-22 14:25: Initial setup
- Created project structure
- Built basic Streamlit UI
- Installed dependencies
- Deployed to localhost:8501

### 2026-07-22 14:40: Docker architecture planning
- Designed two-container architecture
- Created detailed task breakdown
- Defined model configuration
- Planned integration tests

---

## Contact & Support

For questions or issues:
- Check logs: `docker-compose logs`
- Restart system: `docker-compose restart`
- Stop system: `docker-compose down`
- View health: `docker-compose ps`

---

**Next Action**: Review and approve this plan, then proceed with Step 1 (Bonsai Model Acquisition)