"""
Split a combined Keller sermon archive into individual .txt files.
Works with any Keller archive by detecting ALL CAPS title lines
as sermon boundaries.

Usage: python3 split-keller.py input.txt output_folder/
"""

import sys
import re
import os


def is_sermon_title(line, lines, idx):
    """
    Detect sermon title lines. In Keller archives, sermon bodies
    start with an ALL CAPS title line (e.g., "CHILDREN OF THE LIGHT")
    that is:
    - At least 5 characters long
    - All uppercase letters (plus spaces, punctuation)
    - Not a section header like "Sermons by Date"
    - Followed within a few lines by a scripture reference or date
    """
    stripped = line.strip()
    
    # Must be non-empty and at least 5 chars
    if len(stripped) < 5:
        return False
    
    # Must be mostly uppercase letters
    # Allow spaces, commas, colons, apostrophes, hyphens, periods
    alpha_chars = [c for c in stripped if c.isalpha()]
    if len(alpha_chars) < 3:
        return False
    if not all(c.isupper() for c in alpha_chars):
        return False
    
    # Skip known non-sermon headers
    skip_patterns = [
        "SERMONS BY", "TABLE OF CONTENTS", "COPYRIGHT",
        "ALL RIGHTS", "REDEEMER", "ACKNOWLEDGMENT",
    ]
    for pat in skip_patterns:
        if pat in stripped:
            return False
    
    # Look ahead for confirming signals (scripture ref, date, or "This is the Word")
    lookahead = '\n'.join(lines[idx:idx+15]).lower()
    has_scripture = bool(re.search(r'\d+:\d+', lookahead))
    has_date = bool(re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d', lookahead))
    has_word = 'word of the lord' in lookahead or 'scripture' in lookahead or 'reading' in lookahead
    
    return has_scripture or has_date or has_word


def split_sermons(input_path, output_dir):
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()
    
    lines = text.split('\n')
    
    # Find sermon start positions
    sermon_starts = []
    for i, line in enumerate(lines):
        if is_sermon_title(line, lines, i):
            title = line.strip().title()  # Convert "CHILDREN OF THE LIGHT" to "Children Of The Light"
            sermon_starts.append((i, title))
    
    print(f"Found {len(sermon_starts)} sermons")
    
    if len(sermon_starts) == 0:
        print("No sermons detected. Check the file format.")
        return
    
    os.makedirs(output_dir, exist_ok=True)
    
    for idx, (start_line, title) in enumerate(sermon_starts):
        # End is the start of the next sermon, or end of file
        if idx + 1 < len(sermon_starts):
            end_line = sermon_starts[idx + 1][0]
        else:
            end_line = len(lines)
        
        # Extract sermon text
        sermon_text = '\n'.join(lines[start_line:end_line]).strip()
        
        # Create filename from title
        safe_title = re.sub(r'[^\w\s-]', '', title).strip()
        safe_title = re.sub(r'\s+', '-', safe_title)
        filename = f"keller-{safe_title.lower()}.txt"
        
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(sermon_text)
        
        char_count = len(sermon_text)
        print(f"  [{idx+1:02d}] {title} — {char_count:,} chars → {filename}")
    
    print(f"\nDone! {len(sermon_starts)} sermons written to {output_dir}/")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 split-keller.py input.txt output_folder/")
        sys.exit(1)
    
    split_sermons(sys.argv[1], sys.argv[2])