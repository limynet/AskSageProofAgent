"""
Document Parser Module
Supports PDF, DOCX, and TXT file parsing
"""
import PyPDF2
from docx import Document
from pathlib import Path
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class DocumentParser:
    """Parse PDF, DOCX, and TXT files with metadata extraction"""
    
    def __init__(self):
        self.supported_formats = ['.pdf', '.docx', '.txt']
    
    def parse(self, file_path: str) -> Dict[str, any]:
        """
        Parse document and extract text with metadata
        
        Args:
            file_path: Path to document file
            
        Returns:
            Dict with 'text', 'pages', 'metadata'
        """
        ext = Path(file_path).suffix.lower()
        
        if ext == '.pdf':
            return self.parse_pdf(file_path)
        elif ext == '.docx':
            return self.parse_docx(file_path)
        elif ext == '.txt':
            return self.parse_txt(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}. Supported: {self.supported_formats}")
    
    def parse_pdf(self, file_path: str) -> Dict[str, any]:
        """Parse PDF file with page-by-page extraction"""
        try:
            reader = PyPDF2.PdfReader(file_path)
            pages = []
            full_text = ""
            
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text()
                pages.append({
                    'page_number': page_num + 1,
                    'text': page_text
                })
                full_text += page_text + "\n\n"
            
            return {
                'text': full_text,
                'pages': pages,
                'total_pages': len(reader.pages),
                'metadata': {
                    'format': 'pdf',
                    'total_pages': len(reader.pages)
                }
            }
        except Exception as e:
            logger.error(f"PDF parsing failed: {str(e)}")
            raise
    
    def parse_docx(self, file_path: str) -> Dict[str, any]:
        """Parse DOCX file"""
        try:
            doc = Document(file_path)
            paragraphs = []
            full_text = ""
            
            for idx, para in enumerate(doc.paragraphs):
                paragraphs.append({
                    'paragraph_number': idx + 1,
                    'text': para.text
                })
                full_text += para.text + "\n"
            
            return {
                'text': full_text,
                'pages': paragraphs,
                'total_pages': len(paragraphs),
                'metadata': {
                    'format': 'docx',
                    'total_paragraphs': len(paragraphs)
                }
            }
        except Exception as e:
            logger.error(f"DOCX parsing failed: {str(e)}")
            raise
    
    def parse_txt(self, file_path: str) -> Dict[str, any]:
        """Parse TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            lines = text.split('\n')
            
            return {
                'text': text,
                'pages': [{'line_number': i+1, 'text': line} for i, line in enumerate(lines)],
                'total_pages': len(lines),
                'metadata': {
                    'format': 'txt',
                    'total_lines': len(lines)
                }
            }
        except Exception as e:
            logger.error(f"TXT parsing failed: {str(e)}")
            raise