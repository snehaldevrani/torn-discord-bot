"""
API key manager for Torn API.
Handles key rotation, rate limiting, and usage tracking.
"""

import time
from typing import Optional, List

from utils.logger import get_logger

logger = get_logger(__name__)


class APIKeyManager:
    """Manages pool of Torn API keys with rotation and rate limiting."""
    
    def __init__(self, api_keys: List[str]):
        """
        Initialize key manager.
        
        Args:
            api_keys: List of Torn API keys
        """
        if not api_keys:
            raise ValueError("No API keys provided")
        
        self.api_keys = api_keys
        self.current_index = 0
        
        # Track usage per key: {key: {'count': int, 'reset_time': float, 'status': str}}
        self.key_usage = {}
        
        for key in self.api_keys:
            self.key_usage[key] = {
                'count': 0,
                'reset_time': time.time() + 60,
                'status': 'active',  # 'active', 'rate_limited', 'permanently_bad'
                'rate_limited_until': 0
            }
        
        self.total_requests = 0
        self.permanently_bad_keys = set()
        
        logger.info(f"API Key Manager initialized with {len(api_keys)} keys")
    
    def _reset_expired_counters(self):
        """Reset usage counters for keys whose minute has passed."""
        current_time = time.time()
        
        for key in self.key_usage:
            if current_time >= self.key_usage[key]['reset_time']:
                self.key_usage[key]['count'] = 0
                self.key_usage[key]['reset_time'] = current_time + 60
            
            # Reset rate limits
            if current_time >= self.key_usage[key]['rate_limited_until']:
                if self.key_usage[key]['status'] == 'rate_limited':
                    self.key_usage[key]['status'] = 'active'
    
    def get_available_key(self) -> Optional[str]:
        """
        Get next available API key for use.
        Rotates through keys, using each for 40 calls before moving to next.
        
        Returns:
            API key string or None if all exhausted
        """
        self._reset_expired_counters()
        
        current_time = time.time()
        attempts = 0
        max_attempts = len(self.api_keys)
        
        # Try to find available key, starting from current_index
        while attempts < max_attempts:
            key = self.api_keys[self.current_index]
            usage = self.key_usage[key]
            
            # Skip permanently bad keys
            if usage['status'] == 'permanently_bad':
                self.current_index = (self.current_index + 1) % len(self.api_keys)
                attempts += 1
                continue
            
            # Skip rate limited keys
            if usage['status'] == 'rate_limited' and usage['rate_limited_until'] > current_time:
                self.current_index = (self.current_index + 1) % len(self.api_keys)
                attempts += 1
                continue
            
            # Check if key has calls remaining (40 call limit)
            if usage['count'] < 40:
                # Use this key
                self.key_usage[key]['count'] += 1
                self.total_requests += 1
                
                logger.debug(f"Using key {key[:8]}... (call {usage['count']}/40)")
                
                # If key just hit 40, move to next key for next call
                if usage['count'] >= 40:
                    self.current_index = (self.current_index + 1) % len(self.api_keys)
                    logger.debug(f"Key {key[:8]}... exhausted (40/40), rotating to next key")
                
                return key
            
            # Key exhausted, move to next
            self.current_index = (self.current_index + 1) % len(self.api_keys)
            attempts += 1
        
        # All keys exhausted or bad
        logger.warning("⚠️ All API keys exhausted or unavailable this cycle")
        return None
    
    def report_rate_limit(self, api_key: str):
        """
        Mark a key as temporarily rate limited (error 5).
        
        Args:
            api_key: The key that was rate limited
        """
        if api_key in self.key_usage:
            self.key_usage[api_key]['status'] = 'rate_limited'
            self.key_usage[api_key]['rate_limited_until'] = time.time() + 60
            logger.warning(f"⏸️ API key {api_key[:8]}... rate limited (error 5) - skipping for 60s")
    
    def report_invalid_key(self, api_key: str, error_code: int, error_msg: str):
        """
        Mark a key as permanently invalid.
        Handles errors: 2 (incorrect), 13 (inactive), 18 (paused)
        
        Args:
            api_key: The invalid key
            error_code: Torn API error code
            error_msg: Error message
        """
        if api_key in self.key_usage:
            self.key_usage[api_key]['status'] = 'permanently_bad'
            self.permanently_bad_keys.add(api_key)
            logger.error(
                f"❌ API key {api_key[:8]}... permanently removed "
                f"(Error {error_code}: {error_msg})"
            )
    
    def get_stats(self) -> dict:
        """
        Get current usage statistics.
        
        Returns:
            Dict with stats
        """
        current_time = time.time()
        
        active_count = 0
        rate_limited_count = 0
        bad_count = len(self.permanently_bad_keys)
        
        for key in self.api_keys:
            usage = self.key_usage[key]
            
            if usage['status'] == 'permanently_bad':
                continue
            elif usage['status'] == 'rate_limited' and usage['rate_limited_until'] > current_time:
                rate_limited_count += 1
            elif usage['count'] < 40:
                active_count += 1
        
        return {
            'total_keys': len(self.api_keys),
            'active': active_count,
            'rate_limited': rate_limited_count,
            'permanently_bad': bad_count,
            'total_requests': self.total_requests
        }
    
    def reset_stats(self):
        """Reset total request counter (for testing)."""
        self.total_requests = 0


# Global instance
_key_manager: Optional[APIKeyManager] = None


def init_key_manager(api_keys: List[str]):
    """
    Initialize global key manager.
    
    Args:
        api_keys: List of API keys
    """
    global _key_manager
    _key_manager = APIKeyManager(api_keys)


def get_key_manager() -> APIKeyManager:
    """
    Get global key manager instance.
    
    Returns:
        APIKeyManager instance
    """
    if _key_manager is None:
        raise RuntimeError("Key manager not initialized. Call init_key_manager() first.")
    return _key_manager