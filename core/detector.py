"""
Sale detection logic.
Compares individual player bazaar snapshots to detect sales.
"""

from typing import List, Dict, Optional
import asyncio

from database.models import BazaarStateModel, MonitoredItemsModel
from api.weav3r import get_weav3r_client
from utils.logger import get_logger

logger = get_logger(__name__)


class SaleDetector:
    """Detects sales by comparing player bazaar snapshots."""
    
    def __init__(self):
        self.bazaar_model = BazaarStateModel()
        self.weav3r_client = get_weav3r_client()
        self.items_model = MonitoredItemsModel()
    
    async def discover_active_players(self, top_n: int = 10) -> set:
        """
        Discover active players from weav3r marketplace (top N listings).
        
        Args:
            top_n: Number of top listings to check per item
            
        Returns:
            Set of player_ids currently in top listings
        """
        # Get all monitored items
        items = await self.items_model.get_enabled_items()
        
        if not items:
            logger.warning("No items configured for monitoring")
            return set()
        
        logger.info(f"🔍 Scanning weav3r for top {top_n} listings across {len(items)} items...")
        
        # Fetch all items in parallel with semaphore
        semaphore = asyncio.Semaphore(60)
        
        async def fetch_with_semaphore(item):
            async with semaphore:
                return await self.weav3r_client.fetch_bazaar_data(item['item_id'], top_n)
        
        tasks = [fetch_with_semaphore(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect unique player IDs
        discovered_players = set()
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"❌ Failed to fetch item {items[i]['item_name']}: {result}")
                continue
            
            if result:
                for listing in result:
                    discovered_players.add(listing['player_id'])
        
        logger.info(f"✅ Discovered {len(discovered_players)} unique players in top listings")
        return discovered_players
    
    async def detect_sales_for_player(self, player_id: int, player_name: str, current_bazaar: List[dict]) -> List[dict]:
        """
        Detect sales for a single player by comparing bazaar snapshots.
        
        Args:
            player_id: Player's Torn 
            player_name: Player's name (from profile data)

            current_bazaar: Current bazaar items from Torn API
                            [{item_id, quantity, price, name}, ...]
            
        Returns:
            List of detected sales with item_id, quantity_sold, unit_price, total_value
        """
        sales = []
        
        # Get previous snapshot
        previous_snapshot = await self.bazaar_model.get_player_snapshot(player_id)
        
        # If no previous snapshot, save current and return (need 2 cycles)
        if not previous_snapshot:
            await self.bazaar_model.save_player_snapshot(player_id, current_bazaar)
            return sales
        
        # Compare snapshots
        for item in current_bazaar:
            item_id = item['item_id']
            curr_quantity = item['quantity']
            curr_price = item['price']
            
            # Check if item existed in previous snapshot
            if item_id in previous_snapshot:
                prev_quantity = previous_snapshot[item_id]['quantity']
                prev_price = previous_snapshot[item_id]['price']
                
                # Detect quantity decrease (sale)
                if curr_quantity < prev_quantity:
                    quantity_sold = prev_quantity - curr_quantity
                    sale_value = quantity_sold * prev_price
                    
                    sales.append({
                        'player_id': player_id,
                        'player_name': player_name,  # ADD THIS LINE
                        'item_id': item_id,
                        'item_name': item.get('name', f'Item {item_id}'),
                        'quantity_sold': quantity_sold,
                        'unit_price': prev_price,
                        'total_value': sale_value
                    })
                    
                    logger.info(
                        f"💰 SALE: {player_name} {player_id} sold "
                        f"{quantity_sold}x {item.get('name', item_id)} @ ${prev_price:,} = ${sale_value:,}"
                    )
        
        # Check for delisted items (removed from bazaar = full sale)
        for prev_item_id, prev_data in previous_snapshot.items():
            # If item was in previous but not in current = fully sold
            if not any(item['item_id'] == prev_item_id for item in current_bazaar):
                quantity_sold = prev_data['quantity']
                sale_value = quantity_sold * prev_data['price']
                
                sales.append({
                    'player_id': player_id,
                    'player_name': player_name,  # ADD THIS LINE
                    'item_id': prev_item_id,
                    'item_name': f'Item {prev_item_id}',
                    'quantity_sold': quantity_sold,
                    'unit_price': prev_data['price'],
                    'total_value': sale_value
                })
                
                logger.info(
                    f"💰 DELISTED: {player_name} {player_id} sold entire listing "
                    f"{quantity_sold}x item {prev_item_id} @ ${prev_data['price']:,} = ${sale_value:,}"
                )
        
        # Save current snapshot for next cycle
        await self.bazaar_model.save_player_snapshot(player_id, current_bazaar)
        
        return sales


# Global instance
_detector: SaleDetector = None


def get_detector() -> SaleDetector:
    """
    Get global detector instance.
    
    Returns:
        SaleDetector instance
    """
    global _detector
    if _detector is None:
        _detector = SaleDetector()
    return _detector