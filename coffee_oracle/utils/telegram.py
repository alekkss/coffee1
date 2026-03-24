"""Telegram utilities for message handling."""

import re
from typing import List
from html.parser import HTMLParser

# Telegram message limits
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024


class HTMLValidator(HTMLParser):
    """Validate and fix HTML for Telegram."""
    
    def __init__(self):
        super().__init__()
        self.tag_stack = []
        self.result = []
        self.valid = True
    
    def handle_starttag(self, tag, attrs):
        self.tag_stack.append(tag)
        attrs_str = ''.join(f' {k}="{v}"' for k, v in attrs)
        self.result.append(f'<{tag}{attrs_str}>')
    
    def handle_endtag(self, tag):
        if self.tag_stack and self.tag_stack[-1] == tag:
            self.tag_stack.pop()
            self.result.append(f'</{tag}>')
        else:
            self.valid = False
    
    def handle_data(self, data):
        self.result.append(data)
    
    def get_result(self):
        # Close any unclosed tags
        while self.tag_stack:
            tag = self.tag_stack.pop()
            self.result.append(f'</{tag}>')
        return ''.join(self.result)


def sanitize_telegram_html(text: str) -> str:
    """
    Sanitize HTML for Telegram - fix unclosed/mismatched tags.
    
    Args:
        text: HTML text that may have issues
    
    Returns:
        Valid HTML text for Telegram
    """
    if not text:
        return text
    
    # Allowed Telegram HTML tags
    allowed_tags = {'b', 'i', 'u', 's', 'code', 'pre', 'a'}
    
    # Simple approach: track open tags and ensure proper nesting
    result = []
    tag_stack = []
    i = 0
    
    while i < len(text):
        # Check for tag
        if text[i] == '<':
            # Find end of tag
            end = text.find('>', i)
            if end == -1:
                # No closing >, escape it
                result.append('&lt;')
                i += 1
                continue
            
            tag_content = text[i+1:end]
            
            # Check if closing tag
            if tag_content.startswith('/'):
                tag_name = tag_content[1:].split()[0].lower()
                if tag_name in allowed_tags:
                    # Find matching open tag
                    if tag_stack and tag_stack[-1] == tag_name:
                        tag_stack.pop()
                        result.append(f'</{tag_name}>')
                    else:
                        # Mismatched closing tag - skip it
                        pass
                else:
                    # Unknown tag, escape
                    result.append('&lt;')
                    result.append(tag_content)
                    result.append('&gt;')
            else:
                # Opening tag
                tag_name = tag_content.split()[0].lower()
                # Handle self-closing or tags with attributes
                if ' ' in tag_content:
                    tag_name = tag_content.split()[0].lower()
                
                if tag_name in allowed_tags:
                    tag_stack.append(tag_name)
                    # Preserve original tag with attributes
                    result.append(f'<{tag_content}>')
                else:
                    # Unknown tag, escape
                    result.append('&lt;')
                    result.append(tag_content)
                    result.append('&gt;')
            
            i = end + 1
        else:
            result.append(text[i])
            i += 1
    
    # Close any unclosed tags in reverse order
    while tag_stack:
        tag = tag_stack.pop()
        result.append(f'</{tag}>')
    
    return ''.join(result)


def markdown_to_telegram_html(text: str) -> str:
    """
    Convert Markdown text to Telegram HTML format.
    
    Telegram supports limited HTML: <b>, <i>, <u>, <s>, <code>, <pre>, <a>
    
    Args:
        text: Markdown formatted text
    
    Returns:
        HTML formatted text for Telegram
    """
    if not text:
        return text
    
    # Escape HTML special characters first
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    
    # Convert code blocks first (```code```) - must be before other conversions
    def replace_code_block(match):
        code = match.group(2) or match.group(1)
        # Don't process markdown inside code blocks
        return f'<pre>{code}</pre>'
    
    text = re.sub(r'```(?:\w*\n)?(.*?)```', replace_code_block, text, flags=re.DOTALL)
    
    # Convert inline code (`code`) - must be before bold/italic
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # Convert bold (**text** or __text__) - use non-greedy and handle multiline
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text, flags=re.DOTALL)
    
    # Convert italic (*text* or _text_) - be careful not to match ** or __
    # Only match single * or _ that are not part of ** or __
    text = re.sub(r'(?<!\*)\*(?!\*)([^*]+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_(?!_)([^_]+?)(?<!_)_(?!_)', r'<i>\1</i>', text)
    
    # Convert strikethrough (~~text~~)
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text, flags=re.DOTALL)
    
    # Convert links [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    
    # Remove headers (# ## ### etc) - just keep the text bold
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    
    # Remove horizontal rules (---, ***, ___)
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
    
    # Clean up multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Sanitize to fix any broken HTML
    text = sanitize_telegram_html(text)
    
    return text.strip()


def strip_html_tags(text: str) -> str:
    """
    Remove all HTML tags from text.
    Fallback when HTML parsing fails.
    
    Args:
        text: Text with HTML tags
    
    Returns:
        Plain text without HTML tags
    """
    if not text:
        return text
    
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    clean = clean.replace('&lt;', '<')
    clean = clean.replace('&gt;', '>')
    clean = clean.replace('&amp;', '&')
    return clean


def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """
    Split long message into chunks that fit Telegram limits.
    
    Tries to split at newlines or spaces to avoid breaking words.
    
    Args:
        text: Text to split
        max_length: Maximum length per chunk (default 4096)
    
    Returns:
        List of text chunks
    """
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    # Split by paragraphs first (double newline)
    paragraphs = text.split("\n\n")
    
    for paragraph in paragraphs:
        # If adding this paragraph exceeds limit
        if len(current_chunk) + len(paragraph) + 2 > max_length:
            # Save current chunk if not empty
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            
            # If single paragraph is too long, split by lines
            if len(paragraph) > max_length:
                lines = paragraph.split("\n")
                for line in lines:
                    if len(current_chunk) + len(line) + 1 > max_length:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                            current_chunk = ""
                        
                        # If single line is too long, split by words
                        if len(line) > max_length:
                            words = line.split(" ")
                            for word in words:
                                if len(current_chunk) + len(word) + 1 > max_length:
                                    if current_chunk:
                                        chunks.append(current_chunk.strip())
                                    current_chunk = word + " "
                                else:
                                    current_chunk += word + " "
                        else:
                            current_chunk = line + "\n"
                    else:
                        current_chunk += line + "\n"
            else:
                current_chunk = paragraph + "\n\n"
        else:
            current_chunk += paragraph + "\n\n"
    
    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks if chunks else [text[:max_length]]


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate text to max length with suffix.
    
    Args:
        text: Text to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add if truncated
    
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix
