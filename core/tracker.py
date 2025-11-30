"""
Target tracking logic.
Manages tracked targets, accumulates sale values, and checks profiles.
"""

from typing import List, Optional

from database.models import TrackedTargetsModel
from api.torn import get_torn_client
from utils.logger import get_logger
from database.models import TransactionLogModel
import asyncio

logger = get_logger(__name__)


class TargetTracker:
    """Manages target tracking and profile checking."""
    
    def __init__(self):
        self.targets_model = TrackedTargetsModel()
        self.torn_client = get_torn_client()
        self.transaction_log = TransactionLogModel()

    
    async def process_detected_sales(self, sales: List[dict]):
        """
        Process detected sales and update tracked targets.
    
        Args:
            sales: List of sale dicts from detector
        """
        logger.info(f"🔍 Processing {len(sales)} detected sales...")

        for sale in sales:
            # Skip ItemMarket sales that don't have a player_id
            if sale.get('source') == 'itemmarket' or sale.get('player_id') is None:
                logger.debug(
                    f"Skipping ItemMarket activity: {sale.get('quantity_sold')} "
                    f"{sale.get('item_name')} - no specific seller identified"
                )
                continue
            
            # LOG TRANSACTION TO DATABASE
            await self.transaction_log.log_transaction(
                player_id=sale['player_id'],
                player_name=sale['player_name'],
                item_id=sale['item_id'],
                item_name=sale['item_name'],
                quantity=sale['quantity_sold'],
                unit_price=sale['unit_price'],
                total_value=sale['total_value']
            )
            
            await self.targets_model.add_or_update_target(
                player_id=sale['player_id'],
                player_name=sale['player_name'],
                value_to_add=sale['total_value'],
                item_id=sale['item_id']
            )
            
            # Get updated accumulated value
            target = await self.targets_model.get_target(sale['player_id'])
            accumulated = target['accumulated_value'] if target else sale['total_value']

            # CONSOLE LOG with running total
            logger.info(
                f"💰 {sale['player_name']} ({sale['player_id']}) sold "
                f"{sale['quantity_sold']}x {sale['item_name']} @ ${sale['unit_price']:,} "
                f"= ${sale['total_value']:,} | 💵 Total accumulated: ${accumulated:,}"
            )

            logger.debug(
                f"Updated target {sale['player_name']} ({sale['player_id']}): "
                f"+${sale['total_value']:,}"
            )
                
    async def apply_business_logic(self):
        """
        Apply all business logic to tracked targets:
        - Drop rules (online, mugged, job protection, Cayman, stale)
        - Travel logic (South Africa deductions)
    
        This runs AFTER profile data has been updated.
        """
        all_targets = await self.targets_model.get_all_targets()
    
        if not all_targets:
            return
    
        logger.debug(f"🔍 Applying business logic to {len(all_targets)} targets...")
        
        # Get VIP list from config (never drop these players)
        from core.monitor import get_monitor
        monitor = get_monitor()
        vip_players = set(monitor.config.get('vip_players', []))
    
        for target in all_targets:
            player_id = target['player_id']
            player_name = target['player_name']
            current_accumulated = target['accumulated_value']
        
            # Extract data
            status_state = target.get('status_state', 'Unknown')
            status_description = target.get('status_description', '')
            is_traveling = (status_state == "Abroad")
            last_action_minutes = target.get('last_action_minutes', 999)
            is_online = (last_action_minutes < 2)
        
            # Get previous state
            previous_travel_state = target.get('travel_state', 'Okay')
            sa_deduction_applied = target.get('sa_deduction_applied', 0)
        
            # ========================================
            # CAYMAN ISLANDS - DROP (or reset for VIP)
            # ========================================
            if "Cayman Islands" in status_description:
                if player_id in vip_players:
                    logger.info(
                        f"⭐ VIP {player_name} ({player_id}) in Cayman Islands - "
                        f"Resetting accumulated from ${current_accumulated:,} to $0"
                    )
                    await self.targets_model.update_accumulated_and_travel(player_id, 0)
                    current_accumulated = 0
                else:
                    logger.info(
                        f"💰 {player_name} ({player_id}) traveling to/in Cayman Islands - "
                        f"Dropping target (money storage)"
                    )
                    await self.targets_model.reset_target(player_id)
                    continue
        
            # ========================================
            # SOUTH AFRICA - DEDUCT $20M
            # ========================================
            if "South Africa" in status_description:
                if "Returning" not in status_description and not sa_deduction_applied:
                    logger.info(
                        f"🇿🇦 {player_name} ({player_id}) in/traveling to South Africa - "
                        f"Deducting $20M (Xanax runner). Was: ${current_accumulated:,}"
                    )

                    new_accumulated = current_accumulated - 20_000_000

                    logger.info(
                        f"    Now: ${new_accumulated:,} "
                        f"{'(NEGATIVE - will monitor for more sales)' if new_accumulated < 0 else ''}"
                    )
                
                    await self.targets_model.update_accumulated_and_travel(
                        player_id, 
                        new_accumulated, 
                        sa_deduction_applied=True
                    )
                
                    current_accumulated = new_accumulated
                    sa_deduction_applied = True
        
            # ========================================
            # MUGGED - DROP (or reset for VIP)
            # ========================================
            is_mugged = target.get('status_description', '').startswith('Mugged by')

            if is_mugged:
                mugger = target.get('status_description', '').replace('Mugged by ', '').strip()

                if player_id in vip_players:
                    logger.info(
                        f"⭐ VIP {player_name} ({player_id}) mugged by {mugger} - "
                        f"Resetting accumulated from ${current_accumulated:,} to $0"
                    )
                    await self.targets_model.update_accumulated_and_travel(player_id, 0)
                    current_accumulated = 0
                else:
                    if is_traveling:
                        logger.info(
                            f"💸 {player_name} ({player_id}) mugged by {mugger} while traveling - "
                            f"Dropping (mug protection applies). Lost ${current_accumulated:,}"
                        )
                    else:
                        logger.info(
                            f"💸 {player_name} ({player_id}) mugged by {mugger} - "
                            f"Dropping. Lost ${current_accumulated:,}"
                        )

                    await self.targets_model.reset_target(player_id)
                    continue
        
            # ========================================
            # CLOTHING STORE MUG PROTECTION
            # ========================================
            # Job data is stored in profile_data from torn API
            # We need to check if it's in the target record
            # Actually, we already update this in batch_update_profile_data
            # But job data isn't stored in tracked_targets table
            # We need to add it there OR check it differently

            # For now, skip this check - we'll add job columns to tracked_targets later if needed

            # ========================================
            # ONLINE STATUS
            # ========================================
            if is_online:
                if is_traveling:
                    logger.info(
                        f"✈️ {player_name} ({player_id}) online while traveling - "
                        f"Keep monitoring (${current_accumulated:,})"
                    )
                else:
                    if player_id in vip_players:
                        logger.info(
                            f"⭐ VIP {player_name} ({player_id}) came online - "
                            f"Resetting accumulated from ${current_accumulated:,} to $0"
                        )
                        await self.targets_model.update_accumulated_and_travel(player_id, 0)
                        current_accumulated = 0
                    else:
                        logger.info(
                            f"🟢 {player_name} ({player_id}) came online in Torn - "
                            f"Resetting accumulated ${current_accumulated:,}"
                        )
                        await self.targets_model.reset_target(player_id)
                        continue
        
            # ========================================
            # LANDED BACK IN TORN - RESET SA FLAG
            # ========================================
            if status_state == "Okay" and previous_travel_state == "Abroad":
                logger.info(f"🛬 {player_name} ({player_id}) landed back in Torn")
            
                if sa_deduction_applied:
                    await self.targets_model.reset_sa_deduction(player_id)

            # ========================================
            # FEDERAL JAIL - DROP
            # ========================================
            if status_state == 'Federal':
                logger.debug(f"Skipping Federal player {player_id}")
                await self.targets_model.reset_target(player_id)
                continue
    
        # ========================================
        # DROP STALE TARGETS (no sales for 2 hours, not in top 10)
        # ========================================
        await self._drop_stale_targets_2hr(all_targets)
        
    async def _drop_stale_targets_2hr(self, all_targets: List[dict]):
        """
        Drop targets who haven't made a sale in 2 hours.
        This is called AFTER business logic, so we only drop non-critical targets.
        """
        from datetime import datetime, timedelta

        cutoff_time = datetime.now() - timedelta(hours=2)
    
        for target in all_targets:
            last_sale_time_str = target.get('last_sale_time')
        
            if not last_sale_time_str:
                continue
        
            # Parse last_sale_time
            try:
                last_sale_time = datetime.strptime(last_sale_time_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                logger.warning(f"Invalid last_sale_time format for player {target['player_id']}")
                continue
        
            # Check if stale (2+ hours no sales)
            if last_sale_time < cutoff_time:
                # Get VIP list
                from core.monitor import get_monitor
                monitor = get_monitor()
                vip_players = set(monitor.config.get('vip_players', []))
    
                if target['player_id'] in vip_players:
                    logger.info(
                        f"⭐ VIP {target['player_name']} ({target['player_id']}) stale but keeping "
                        f"(last sale: {last_sale_time_str})"
                    )
                    continue
    
                logger.info(
                    f"🗑️ Dropping stale target {target['player_name']} ({target['player_id']}) - "
                    f"No sales in 2+ hours (last sale: {last_sale_time_str})"
                )
                await self.targets_model.reset_target(target['player_id'])

    async def get_targets_for_alerts(self, min_accumulated: int, min_inactivity: int) -> List[dict]:
        """
        Get targets that meet all alert criteria.

        Args:
            min_accumulated: Minimum accumulated value
            min_inactivity: Minimum inactivity in minutes
        
        Returns:
            List of targets ready for alerts
        """
        # Get targets from database that meet criteria
        targets = await self.targets_model.get_targets_for_alerts(
            min_accumulated=min_accumulated,
            min_inactivity=min_inactivity
        )
    
        if targets:
            logger.info(f"🎯 {len(targets)} targets ready for alerts")
    
        return targets
    
    async def get_active_targets_count(self) -> int:
        """
        Get count of active tracked targets.
        
        Returns:
            Number of targets
        """
        targets = await self.targets_model.get_all_targets()
        return len(targets)
    
    async def get_total_tracked_value(self) -> int:
        """
        Get total accumulated value across all targets.
        
        Returns:
            Total value in dollars
        """
        targets = await self.targets_model.get_all_targets()
        return sum(target['accumulated_value'] for target in targets)


# Global instance
_tracker: Optional[TargetTracker] = None


def get_tracker() -> TargetTracker:
    """
    Get global tracker instance.
    
    Returns:
        TargetTracker instance
    """
    global _tracker
    if _tracker is None:
        _tracker = TargetTracker()
    return _tracker