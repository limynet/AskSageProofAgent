"""
AskSage Proof Agent - Streamlit Application
Two-container architecture with Bonsai (primary) and AskSage (fallback) support
"""
import streamlit as st
import os
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from llm_client import LLMClient, create_llm_client
from document_parser import DocumentParser
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="AskSage Proof Agent",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for professional government aesthetic
st.markdown("""
<style>
    .stApp {
        max-width: 1000px;
        margin: 0 auto;
    }
    .main-header {
        text-align: center;
        padding: 2rem 0;
    }
    .status-success {
        color: #16c784;
        font-weight: bold;
    }
    .status-error {
        color: #ff6b6b;
        font-weight: bold;
    }
    .status-warning {
        color: #ffd93d;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# Session state initialization
if 'llm_client' not in st.session_state:
    st.session_state.llm_client = None
if 'doc_parser' not in st.session_state:
    st.session_state.doc_parser = DocumentParser()
if 'uploaded_file' not in st.session_state:
    st.session_state.uploaded_file = None
if 'parsed_content' not in st.session_state:
    st.session_state.parsed_content = None

def initialize_llm_client():
    """Initialize LLM client with current configuration"""
    try:
        client = create_llm_client()
        model_info = client.get_model_info()
        st.session_state.llm_client = client
        return True, model_info
    except Exception as e:
        st.session_state.llm_client = None
        return False, {"error": str(e)}

def test_llm_connection():
    """Test LLM service connectivity"""
    if st.session_state.llm_client is None:
        success, info = initialize_llm_client()
        if not success:
            return False, info
    return st.session_state.llm_client.test_connection(), st.session_state.llm_client.get_model_info()

def main():
    """Main application"""
    
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>📄 AskSage Proof Agent</h1>
        <p>Automated Document Review with APA 7th Edition & ARI Standards</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar - Configuration & Status
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # LLM Status
        st.subheader("LLM Service Status")
        if st.button("🔍 Test Connection"):
            with st.spinner("Testing connection..."):
                success, info = test_llm_connection()
                
                if success:
                    st.markdown(f'<p class="status-success">✅ Connected: {info["model_name"]}</p>', unsafe_allow_html=True)
                    st.json(info)
                else:
                    st.markdown(f'<p class="status-error">❌ Connection Failed</p>', unsafe_allow_html=True)
                    if "error" in info:
                        st.error(info["error"])
        
        # Display current status
        if st.session_state.llm_client:
            info = st.session_state.llm_client.get_model_info()
            st.markdown(f'<p class="status-success">✅ Active: {info["model_name"]}</p>', unsafe_allow_html=True)
        else:
            st.markdown('<p class="status-warning">⚠️ Not Connected</p>', unsafe_allow_html=True)
        
        st.divider()
        
        # Manual model selection
        st.subheader("Model Selection")
        model_choice = st.selectbox(
            "Select LLM Provider",
            ["bonsai", "asksage"],
            help="Bonsai = Local 1.7B (free), AskSage = GPT-5.1 Gov (API key required)"
        )
        
        if st.button("🔄 Switch Model"):
            try:
                st.session_state.llm_client = LLMClient(model_type=model_choice)
                st.success(f"Switched to {model_choice.upper()}")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to switch: {str(e)}")
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("📤 Document Upload")
        
        # File upload
        uploaded_file = st.file_uploader(
            "Upload manuscript for review",
            type=['pdf', 'docx', 'txt'],
            help="Supported formats: PDF, DOCX, TXT"
        )
        
        if uploaded_file:
            st.session_state.uploaded_file = uploaded_file
            
            # Save uploaded file
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            
            file_path = data_dir / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            st.success(f"✅ File uploaded: {uploaded_file.name}")
            
            # Parse document
            try:
                with st.spinner("Parsing document..."):
                    st.session_state.parsed_content = st.session_state.doc_parser.parse(str(file_path))
                
                # Display parsing results
                st.subheader("📊 Document Information")
                metadata = st.session_state.parsed_content['metadata']
                col_info1, col_info2, col_info3 = st.columns(3)
                
                with col_info1:
                    st.metric("Format", metadata['format'].upper())
                with col_info2:
                    st.metric("Pages/Lines", metadata.get('total_pages', metadata.get('total_lines', 'N/A')))
                with col_info3:
                    st.metric("Characters", len(st.session_state.parsed_content['text']))
                
            except Exception as e:
                st.error(f"❌ Failed to parse document: {str(e)}")
    
    with col2:
        st.header("🧪 LLM Testing")
        
        # Simple test interface
        test_prompt = st.text_area(
            "Test Prompt",
            value="Explain what APA 7th Edition citation format is.",
            height=100
        )
        
        if st.button("🚀 Test LLM"):
            if not st.session_state.llm_client:
                st.warning("Please connect to LLM service first")
            else:
                with st.spinner("Generating response..."):
                    try:
                        messages = [
                            {"role": "system", "content": "You are an expert in academic writing and APA 7th Edition."},
                            {"role": "user", "content": test_prompt}
                        ]
                        
                        response = st.session_state.llm_client.chat_completion(
                            messages=messages,
                            temperature=0.3,
                            max_tokens=500
                        )
                        
                        st.subheader("📝 Response")
                        st.markdown(response)
                        
                    except Exception as e:
                        st.error(f"❌ LLM request failed: {str(e)}")
    
    # Footer
    st.divider()
    st.markdown("""
    <div style='text-align: center; color: #666;'>
        <small>AskSage Proof Agent | Bonsai 1.7B (Local) + AskSage GPT-5.1 Gov (Fallback) | Two-Container Architecture</small>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()