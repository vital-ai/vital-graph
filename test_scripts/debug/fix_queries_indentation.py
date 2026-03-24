#!/usr/bin/env python3
"""
Quick fix for the indentation issues in postgresql_space_queries.py
"""

import re

def fix_indentation():
    """Fix the indentation issues in the queries file."""
    
    file_path = "/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/db/postgresql/space/postgresql_space_queries.py"
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Find the problematic section and fix it
    # Look for the cursor context manager section
    pattern = r'(with conn\.cursor\(\) as cursor:.*?)(\n\s+# Helper function)'
    
    def fix_cursor_block(match):
        cursor_line = match.group(1)
        rest = match.group(2)
        
        # Fix the indentation in the cursor block
        fixed_cursor = cursor_line.replace('                        ', '                    ')
        return fixed_cursor + rest
    
    # Apply the fix
    fixed_content = re.sub(pattern, fix_cursor_block, content, flags=re.DOTALL)
    
    # Additional fixes for specific indentation issues
    fixed_content = fixed_content.replace('                        if not is_unbound', '                    if not is_unbound')
    fixed_content = fixed_content.replace('                            if is_regex_term', '                        if is_regex_term')
    fixed_content = fixed_content.replace('                                # Use PostgreSQL', '                            # Use PostgreSQL')
    fixed_content = fixed_content.replace('                                where_conditions.append', '                            where_conditions.append')
    fixed_content = fixed_content.replace('                                params.append', '                            params.append')
    fixed_content = fixed_content.replace('                                params.extend', '                            params.extend')
    fixed_content = fixed_content.replace('                                self.logger.debug', '                            self.logger.debug')
    fixed_content = fixed_content.replace('                            else:', '                        else:')
    fixed_content = fixed_content.replace('                                s_text, s_type', '                            s_text, s_type')
    fixed_content = fixed_content.replace('                                p_text, p_type', '                            p_text, p_type')
    fixed_content = fixed_content.replace('                                o_text, o_type', '                            o_text, o_type')
    fixed_content = fixed_content.replace('                                c_text, c_type', '                            c_text, c_type')
    fixed_content = fixed_content.replace('                                # Add language', '                            # Add language')
    fixed_content = fixed_content.replace('                                    where_conditions.append', '                                where_conditions.append')
    fixed_content = fixed_content.replace('                                    params.append', '                                params.append')
    
    # Fix the remaining sections
    fixed_content = fixed_content.replace('                        # Add predicate condition', '                    # Add predicate condition')
    fixed_content = fixed_content.replace('                        # Add object condition', '                    # Add object condition')
    fixed_content = fixed_content.replace('                        # Add context condition', '                    # Add context condition')
    
    with open(file_path, 'w') as f:
        f.write(fixed_content)
    
    print("✅ Fixed indentation issues in postgresql_space_queries.py")

if __name__ == "__main__":
    fix_indentation()
