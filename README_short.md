# AskSageProofAgent Local

Lightweight manuscript review system using local LLM (Bonsai 1.7B).

## Project Structure

```
AskSageProofAgent_Local/
├── app.py                 # Main Streamlit application
├── requirements.txt       # Python dependencies
├── configs/
│   └── .env              # API configuration
├── src/
│   ├── llm_client.py     # LLM API client
│   ├── document_parser.py # Document extraction
│   └── review_agents.py  # Review agent logic
├── data/                 # Uploaded documents
├── models/               # Bonsai model files
└── docs/                 # Documentation
```

## Quick Start

### 1. Install Dependencies
```bash
cd AskSageProofAgent_Local
pip install -r requirements.txt
```

### 2. Configure API
Edit `configs/.env`:
- Use existing asksage.ai setup for quick testing
- Configure local Bonsai endpoint later

### 3. Run Application
```bash
streamlit run app.py
```

## Development Plan

### Phase 1: Local Prototype (Current)
- [x] Basic Streamlit UI
- [ ] Document extraction (PDF/DOCX/TXT)
- [ ] LLM integration (Bonsai 1.7B)
- [ ] Basic citation review
- [ ] APA style check

### Phase 2: Foundry PLTR Migration
- Migrate to Palantir Foundry platform
- Use unlimited LLM API
- Scale for production use

### Phase 3: Architecture Enhancement
- Multi-agent orchestration
- Advanced review workflows
- Performance optimization

## Model Information

**Bonsai 1.7B**: Lightweight, quantized model optimized for local inference
- GitHub: https://github.com/PrismML-Eng/Bonsai-demo
- HuggingFace: https://huggingface.co/collections/prism-ml/bonsai

## Notes

- All code and documentation must be in English
- Built for ARI Publications Manual compliance
- Designed for non-technical users (point-and-click UI)