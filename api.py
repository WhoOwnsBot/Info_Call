import requests
import json
import urllib.parse
import logging
from typing import Dict, Any, List, Optional
from config import API_URL, API_KEY, MAX_QUERY_LENGTH

logger = logging.getLogger(__name__)

class SecureAPI:
    """Secure API wrapper with validation and error handling"""
    
    def __init__(self):
        self.base_url = API_URL
        self.api_key = API_KEY
        self.timeout = 15
        self.max_retries = 3
        
        if not self.base_url or not self.api_key:
            raise ValueError("API_URL and API_KEY must be configured")
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'OSINTBot/3.0',
            'Accept': 'application/json'
        })
        
        logger.info("✅ API client initialized")
    
    def search(self, query: str) -> Dict[str, Any]:
        if not query or len(query) > MAX_QUERY_LENGTH:
            return {"error": "Invalid query length"}
        
        query = self._sanitize_query(query)
        encoded_query = urllib.parse.quote(query)
        url = f"{self.base_url}?query={encoded_query}&key={self.api_key}"
        
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, timeout=self.timeout)
                
                if response.status_code == 200:
                    return self._parse_response(response)
                elif response.status_code == 429:
                    logger.warning(f"Rate limited by API: {response.status_code}")
                    time.sleep(2 ** attempt)
                    continue
                else:
                    return {"error": f"API Error: {response.status_code}"}
                    
            except requests.exceptions.Timeout:
                logger.warning(f"API timeout (attempt {attempt + 1})")
                if attempt == self.max_retries - 1:
                    return {"error": "API timeout after retries"}
                continue
                
            except requests.exceptions.ConnectionError:
                logger.warning(f"API connection error (attempt {attempt + 1})")
                if attempt == self.max_retries - 1:
                    return {"error": "API connection failed"}
                continue
                
            except Exception as e:
                logger.error(f"API error: {e}")
                return {"error": str(e)}
        
        return {"error": "API request failed"}
    
    def _parse_response(self, response: requests.Response) -> Dict[str, Any]:
        try:
            data = response.json()
            
            if not isinstance(data, dict):
                return {"error": "Invalid API response format"}
            
            if data.get('status') == False:
                error_msg = data.get('error', 'Unknown API error')
                return {"error": error_msg}
            
            if 'data' in data:
                return data.get('data', {})
            
            return data
            
        except json.JSONDecodeError:
            return {"error": "Invalid JSON response from API"}
        except Exception as e:
            logger.error(f"Response parsing error: {e}")
            return {"error": f"Response parsing error: {str(e)}"}
    
    def _sanitize_query(self, query: str) -> str:
        query = ''.join(char for char in query if ord(char) >= 32 or ord(char) in [9, 10, 13])
        query = query.replace('\x00', '')
        return query.strip()
    
    def extract_records(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        records = []
        
        if not isinstance(data, dict):
            return records
        
        for source_name, source_data in data.items():
            if isinstance(source_data, dict):
                recs = source_data.get("records", [])
                if isinstance(recs, list):
                    for record in recs:
                        if isinstance(record, dict):
                            if record.get('Phone') or record.get('Name'):
                                records.append(record)
        
        return records

# Create singleton instance
api_client = SecureAPI()

# Backward compatibility functions
def search_api(query):
    return api_client.search(query)

def extract_records(data):
    return api_client.extract_records(data)