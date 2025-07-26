import logging
from typing import List, Dict, Any, Optional, Tuple
import re

class PostgreSQLSparqlExecutor:
    """
    PostgreSQL SPARQL SQL Execution Handler.
    
    This class handles all SQL query execution, result formatting, and cleanup logic
    for the modular SPARQL implementation. It provides a clean interface for executing
    SQL queries against PostgreSQL databases with proper error handling and result formatting.
    """
    
    def __init__(self, space_impl, logger: Optional[logging.Logger] = None):
        """
        Initialize the SQL executor.
        
        Args:
            space_impl: PostgreSQL space implementation for database connections
            logger: Optional logger instance
        """
        self.space_impl = space_impl
        self.logger = logger or logging.getLogger(__name__)


    async def execute_sql_query(self, sql_query: str) -> List[Dict[str, Any]]:
        """Execute SQL query and return results."""
        try:
            # Clean up SQL before execution to fix common issues
            cleaned_sql = self.cleanup_sql_before_execution(sql_query)
            
            # Use the space_impl's get_connection method to get a database connection
            with self.space_impl.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(cleaned_sql)
                    
                    # Check if this is a SELECT query that returns results
                    query_type = cleaned_sql.strip().upper().split()[0]
                    
                    if query_type == 'SELECT':
                        # Get column names
                        columns = [desc[0] for desc in cursor.description] if cursor.description else []
                        
                        # Fetch all results
                        rows = cursor.fetchall()
                        
                        # Convert to list of dictionaries
                        results = []
                        for row in rows:
                            if isinstance(row, dict):
                                # Row is already a dictionary (some cursor configurations)
                                results.append(row)
                            else:
                                # Row is a tuple/list - convert to dictionary
                                result_dict = {}
                                for i, value in enumerate(row):
                                    if i < len(columns):
                                        result_dict[columns[i]] = value
                                results.append(result_dict)
                        
                        return results
                    else:
                        # For INSERT/UPDATE/DELETE operations, return row count information
                        rows_affected = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
                        self.logger.debug(f"Non-SELECT operation completed successfully: {query_type}, rows affected: {rows_affected}")
                        
                        # Return a result that indicates success and rows affected
                        # This is more appropriate than an empty list for modification operations
                        return [{'operation': query_type, 'rows_affected': rows_affected}]
                
        except Exception as e:
            self.logger.error(f"Error executing SQL query: {e}")
            self.logger.error(f"SQL query was: {sql_query}")
            raise
    

    def cleanup_sql_before_execution(self, sql_query: str) -> str:
        """Simple SQL cleanup to remove duplicate FROM keywords.
        
        Strategy: FROM keywords should be added aggressively during SQL generation.
        This cleanup only removes duplicate FROM keywords at the end.
        
        Args:
            sql_query: Raw SQL query that may have duplicate FROM keywords
            
        Returns:
            Cleaned SQL query with duplicate FROM keywords removed
        """
        try:
            # print(f"🔧 SQL CLEANUP: Processing SQL...")
            # print(f"🔧 ORIGINAL SQL:\n{sql_query}")
            self.logger.debug(f"SQL cleanup: removing duplicate FROM keywords")
            
            # Split SQL into lines for processing
            lines = sql_query.split('\n')
            cleaned_lines = []
            
            for line in lines:
                stripped = line.strip()
                
                # Fix duplicate FROM keywords
                if stripped.upper().startswith('FROM FROM'):
                    # Remove duplicate FROM keywords
                    fixed_line = stripped[5:].strip()  # Remove first 'FROM '
                    cleaned_lines.append(f"FROM {fixed_line}")
                    print(f"🔧   Fixed duplicate FROM: '{stripped}' -> 'FROM {fixed_line}'")
                    self.logger.debug(f"Fixed duplicate FROM: {stripped} -> FROM {fixed_line}")
                else:
                    cleaned_lines.append(line)
            
            cleaned_sql = '\n'.join(cleaned_lines)
            
            # Log the cleanup if changes were made
            if cleaned_sql != sql_query:
                # print(f"🔧 SQL cleanup applied: removed duplicate FROM keywords")
                self.logger.debug(f"SQL cleanup applied: removed duplicate FROM keywords")
            
            return cleaned_sql
            
        except Exception as e:
            self.logger.warning(f"Error during SQL cleanup: {e}. Using original SQL.")
            return sql_query
    
    async def execute_sql_query_with_params(self, query: str, params: tuple) -> List[Dict[str, Any]]:
        """
        Execute a parameterized SQL query.
        
        Args:
            query: SQL query with parameter placeholders
            params: Parameter values
            
        Returns:
            List[Dict[str, Any]]: Query results (empty list for INSERT/DELETE/UPDATE operations)
        """
        try:
            # Use the space_impl's get_connection method to get a database connection
            with self.space_impl.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    
                    # Check if this is a SELECT query that returns results
                    query_type = query.strip().upper().split()[0]
                    
                    if query_type == 'SELECT':
                        # Get column names
                        columns = [desc[0] for desc in cursor.description] if cursor.description else []
                        
                        # Fetch all results
                        rows = cursor.fetchall()
                        
                        # Convert to list of dictionaries
                        results = []
                        for row in rows:
                            if isinstance(row, dict):
                                # Row is already a dictionary (some cursor configurations)
                                results.append(row)
                            else:
                                # Row is a tuple/list - convert to dictionary
                                result_dict = {}
                                for i, value in enumerate(row):
                                    if i < len(columns):
                                        result_dict[columns[i]] = value
                                results.append(result_dict)
                        
                        return results
                    else:
                        # For INSERT/UPDATE/DELETE operations, return row count information
                        rows_affected = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
                        self.logger.debug(f"Non-SELECT operation completed successfully: {query_type}, rows affected: {rows_affected}")
                        
                        # Return a result that indicates success and rows affected
                        return [{'operation': query_type, 'rows_affected': rows_affected}]
                        
        except Exception as e:
            # Handle specific database errors
            if "didn't produce records" in str(e):
                self.logger.debug(f"Non-SELECT operation completed successfully: {query_type}")
                return []
            else:
                self.logger.error(f"Error executing parameterized SQL query: {e}")
                self.logger.error(f"Query: {query}")
                self.logger.error(f"Params: {params}")
                raise
    
    def validate_sql_query(self, sql_query: str) -> bool:
        """
        Validate basic SQL query structure.
        
        Args:
            sql_query: SQL query to validate
            
        Returns:
            bool: True if query appears valid, False otherwise
        """
        try:
            if not sql_query or not sql_query.strip():
                return False
            
            # Basic validation - check for SQL injection patterns
            dangerous_patterns = [
                r';\s*DROP\s+',
                r';\s*DELETE\s+FROM\s+(?!.*WHERE)',
                r';\s*UPDATE\s+.*SET\s+.*(?!.*WHERE)',
                r'UNION\s+SELECT.*--',
                r'\bEXEC\s*\(',
                r'\bEVAL\s*\(',
            ]
            
            for pattern in dangerous_patterns:
                if re.search(pattern, sql_query, re.IGNORECASE):
                    self.logger.warning(f"Potentially dangerous SQL pattern detected: {pattern}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating SQL query: {e}")
            return False
    
    def estimate_query_complexity(self, sql_query: str) -> dict:
        """
        Estimate the complexity of a SQL query.
        
        Args:
            sql_query: SQL query to analyze
            
        Returns:
            dict: Complexity metrics
        """
        try:
            complexity = {
                'joins': 0,
                'subqueries': 0,
                'unions': 0,
                'ctes': 0,
                'aggregates': 0,
                'estimated_complexity': 'low'
            }
            
            query_upper = sql_query.upper()
            
            # Count different SQL constructs
            complexity['joins'] = len(re.findall(r'\bJOIN\b', query_upper))
            complexity['subqueries'] = len(re.findall(r'\(\s*SELECT\b', query_upper))
            complexity['unions'] = len(re.findall(r'\bUNION\b', query_upper))
            complexity['ctes'] = len(re.findall(r'\bWITH\b', query_upper))
            complexity['aggregates'] = len(re.findall(r'\b(COUNT|SUM|AVG|MIN|MAX|GROUP_CONCAT)\s*\(', query_upper))
            
            # Estimate overall complexity
            total_complexity = (
                complexity['joins'] * 2 +
                complexity['subqueries'] * 3 +
                complexity['unions'] * 2 +
                complexity['ctes'] * 2 +
                complexity['aggregates'] * 1
            )
            
            if total_complexity <= 3:
                complexity['estimated_complexity'] = 'low'
            elif total_complexity <= 8:
                complexity['estimated_complexity'] = 'medium'
            else:
                complexity['estimated_complexity'] = 'high'
            
            return complexity
            
        except Exception as e:
            self.logger.error(f"Error estimating query complexity: {e}")
            return {'estimated_complexity': 'unknown'}
    
    def format_sql_for_logging(self, sql_query: str, max_length: int = 500) -> str:
        """
        Format SQL query for logging purposes.
        
        Args:
            sql_query: SQL query to format
            max_length: Maximum length for logged query
            
        Returns:
            str: Formatted SQL query
        """
        try:
            # Clean up whitespace
            formatted = re.sub(r'\s+', ' ', sql_query.strip())
            
            # Truncate if too long
            if len(formatted) > max_length:
                formatted = formatted[:max_length] + '...'
            
            return formatted
            
        except Exception as e:
            self.logger.error(f"Error formatting SQL for logging: {e}")
            return sql_query[:max_length] if len(sql_query) > max_length else sql_query
    
    def extract_table_names(self, sql_query: str) -> List[str]:
        """
        Extract table names from a SQL query.
        
        Args:
            sql_query: SQL query to analyze
            
        Returns:
            List[str]: List of table names found in the query
        """
        try:
            table_names = set()
            
            # Pattern to match table names after FROM and JOIN
            patterns = [
                r'\bFROM\s+([\w_]+)',
                r'\bJOIN\s+([\w_]+)',
                r'\bINTO\s+([\w_]+)',
                r'\bUPDATE\s+([\w_]+)',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, sql_query, re.IGNORECASE)
                table_names.update(matches)
            
            return list(table_names)
            
        except Exception as e:
            self.logger.error(f"Error extracting table names: {e}")
            return []
    
    def get_query_type(self, sql_query: str) -> str:
        """
        Determine the type of SQL query.
        
        Args:
            sql_query: SQL query to analyze
            
        Returns:
            str: Query type (SELECT, INSERT, UPDATE, DELETE, etc.)
        """
        try:
            query_type = sql_query.strip().upper().split()[0]
            return query_type
        except Exception as e:
            self.logger.error(f"Error determining query type: {e}")
            return 'UNKNOWN'
    
    def build_parameterized_query(self, base_query: str, params: Dict[str, Any]) -> Tuple[str, tuple]:
        """
        Build a parameterized query from a base query and parameters.
        
        Args:
            base_query: Base SQL query with named placeholders
            params: Dictionary of parameter values
            
        Returns:
            Tuple[str, tuple]: Parameterized query and parameter tuple
        """
        try:
            # Convert named parameters to positional parameters
            param_values = []
            parameterized_query = base_query
            
            for key, value in params.items():
                placeholder = f":{key}"
                if placeholder in parameterized_query:
                    parameterized_query = parameterized_query.replace(placeholder, "%s")
                    param_values.append(value)
            
            return parameterized_query, tuple(param_values)
            
        except Exception as e:
            self.logger.error(f"Error building parameterized query: {e}")
            return base_query, tuple()

