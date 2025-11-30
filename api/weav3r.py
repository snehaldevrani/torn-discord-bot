"""
Weav3r API client using curl-cffi for Cloudflare bypass.
"""

from curl_cffi.requests import AsyncSession
from typing import Optional, List

from utils.logger import get_logger

logger = get_logger(__name__)


class Weav3rClient:
    """Client for Weav3r bazaar API with Cloudflare bypass."""
    
    def __init__(self, base_url: str = "https://weav3r.dev/api/marketplace", timeout: int = 15):
        self.base_url = base_url
        self.timeout = timeout
        self.session: Optional[AsyncSession] = None
    
    async def _get_session(self) -> AsyncSession:
        """Get or create curl-cffi session."""
        if self.session is None:
            self.session = AsyncSession(
                impersonate="chrome120",  # Critical: makes requests look like Chrome
                timeout=self.timeout
            )
        return self.session
    
    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def fetch_bazaar_data(self, item_id: int, top_n: int = 10) -> Optional[List[dict]]:
        """
        Fetch bazaar listings for an item.
        
        Args:
            item_id: Torn item ID
            top_n: Number of top listings to return
            
        Returns:
            List of listing dicts or None on error
        """
        url = f"{self.base_url}/{item_id}"
        session = await self._get_session()
        
        try:
            response = await session.get(url)
            
            if response.status_code == 403:
                logger.error(f"❌ Cloudflare blocked request for item {item_id} (403)")
                return None
            
            if response.status_code != 200:
                logger.error(
                    f"❌ Weav3r API returned status {response.status_code} for item {item_id}. "
                    f"Response: {response.text[:200]}"
                )
                return None
            
            data = response.json()
            
            # Extract listings
            listings = data.get('listings', [])
            
            if not listings:
                logger.debug(f"No bazaar listings found for item {item_id}")
                return []
            
            # Take only top N (already sorted by price ascending)
            top_listings = listings[:top_n]
            
            # Format listings
            formatted = []
            for listing in top_listings:
                formatted.append({
                    'item_id': listing.get('item_id'),
                    'player_id': listing.get('player_id'),
                    'player_name': listing.get('player_name'),
                    'quantity': listing.get('quantity'),
                    'price': listing.get('price')
                })
            
            logger.debug(f"✅ Fetched {len(formatted)} bazaar listings for item {item_id}")
            return formatted
        
        except Exception as e:
            logger.error(f"❌ Error fetching bazaar data for item {item_id}: {e}", exc_info=True)
            return None


# Global instance
_weav3r_client: Optional[Weav3rClient] = None


def get_weav3r_client() -> Weav3rClient:
    """Get global Weav3r client instance."""
    global _weav3r_client
    if _weav3r_client is None:
        _weav3r_client = Weav3rClient()
    return _weav3r_client