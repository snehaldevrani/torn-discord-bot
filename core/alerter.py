"""
Alert generation and sending.
Creates Discord embeds and sends alerts to channel.
"""

import discord
import json
from typing import List, Optional

from database.models import TransactionLogModel

from database.models import AlertLogModel, MonitoredItemsModel, TrackedTargetsModel
from utils.logger import get_logger
from utils.formatters import format_alert_embed_data

logger = get_logger(__name__)


class Alerter:
    """Handles alert generation and Discord sending."""
    
    def __init__(self, discord_channel: Optional[discord.TextChannel] = None, config: dict = None):
        """
        Initialize alerter.
        
        Args:
            discord_channel: Discord channel to send alerts to
            config: Config dict with alert settings
        """
        self.channel = discord_channel
        self.config = config or {}
        self.alert_log = AlertLogModel()
        self.items_model = MonitoredItemsModel()
        self.targets_model = TrackedTargetsModel()
    
    def set_channel(self, channel: discord.TextChannel):
        """
        Set Discord channel for alerts.
        
        Args:
            channel: Discord channel
        """
        self.channel = channel
        logger.info(f"Alert channel set to: {channel.name} ({channel.id})")
    
    async def send_alerts(self, targets: List[dict]):
        """
        Send alerts for all targets.
        
        Args:
            targets: List of target dicts ready for alerts
        """
        if not targets:
            return
        
        if not self.channel:
            logger.error("No Discord channel set, cannot send alerts")
            return
        
        # Get item names mapping
        item_names = await self.items_model.get_item_names_map()
        
        logger.info(f"Sending {len(targets)} alerts")
        
        for target in targets:
            await self._send_single_alert(target, item_names)
    
    async def _send_single_alert(self, target: dict, item_names: dict):
        """
        Send single alert for a target.
        
        Args:
            target: Target dict
            item_names: Item ID to name mapping
        """
        try:
            
            # GET TRANSACTION HISTORY
            transaction_log = TransactionLogModel()
            transactions = await transaction_log.get_player_transactions(target['player_id'])

            # LOG FULL HISTORY TO CONSOLE
            logger.info("=" * 60)
            logger.info(f"🚨 ALERT: {target['player_name']} ({target['player_id']}) - ${target['accumulated_value']:,}")
            logger.info("📋 TRANSACTION HISTORY:")
        
            for txn in transactions:
                logger.info(
                    f"  [{txn['detected_at']}] {txn['quantity']}x {txn['item_name']} "
                    f"@ ${txn['unit_price']:,} = ${txn['total_value']:,}"
                )
        
            logger.info("=" * 60)
            
            # Parse items_breakdown if it's a JSON string
            if 'sales_breakdown' in target and isinstance(target['sales_breakdown'], str):
                try:
                    target['sales_breakdown'] = json.loads(target['sales_breakdown'])
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse sales_breakdown for player {target['player_id']}")
                    target['sales_breakdown'] = {}
            
            # Format embed data
            embed_data = format_alert_embed_data(
                target=target,
                config=self.config,
                item_names=item_names
            )
            
            # Create Discord embed
            embed = discord.Embed(
                title=embed_data['title'],
                color=discord.Color.red(),
                timestamp=embed_data['timestamp']
            )
            
            # Add fields
            embed.add_field(
                name="👤 Player",
                value=embed_data['player_info'],
                inline=False
            )
            
            embed.add_field(
                name="💰 Cash on Hand",
                value=f"**{embed_data['cash_short']}** ({embed_data['cash_full']})",
                inline=True
            )
            
            embed.add_field(
                name="⏱️ Last Action",
                value=embed_data['time_info'],
                inline=True
            )
            
            embed.add_field(
                name="📶 Activity Status",
                value=embed_data['status_display_text'],
                inline=True
            )

            embed.add_field(
                name="📍 Game Status",
                value=embed_data['status_display'],
                inline=True
            )
            
            # Add breakdown if multiple items
            if embed_data['breakdown']:
                embed.add_field(
                    name="📦 Sales Breakdown",
                    value=embed_data['breakdown'],
                    inline=False
                )
            
            # Add footer
            embed.set_footer(text=f"Player ID: {embed_data['player_id']}")
            
            # Create view with attack button
            view = discord.ui.View(timeout=None)
            button = discord.ui.Button(
                label="🎯 ATTACK NOW",
                style=discord.ButtonStyle.danger,
                url=embed_data['attack_url']
            )
            view.add_item(button)
            
            # Send to Discord
            await self.channel.send(embed=embed, view=view)
            
            # Log alert
            await self.alert_log.log_alert(
                player_id=target['player_id'],
                player_name=target['player_name'],
                accumulated_value=target['accumulated_value'],
                last_action_minutes=target['last_action_minutes'],
                status_state=target['status_state']
            )
            
            # Update last_alerted timestamp AND value (CRITICAL CHANGE)
            await self.targets_model.update_last_alerted(
                target['player_id'], 
                target['accumulated_value']  # Pass the value we just alerted
            )
            
            logger.info(
                f"Alert sent: {target['player_name']} ({target['player_id']}) - "
                f"${target['accumulated_value']:,}"
            )
        
        except Exception as e:
            logger.error(f"Failed to send alert for player {target['player_id']}: {e}")
    
    async def send_info_message(self, message: str):
        """
        Send informational message to channel.
        
        Args:
            message: Message text
        """
        if not self.channel:
            logger.warning("No Discord channel set")
            return
        
        try:
            embed = discord.Embed(
                description=message,
                color=discord.Color.blue()
            )
            await self.channel.send(embed=embed)
        
        except Exception as e:
            logger.error(f"Failed to send info message: {e}")
    
    async def send_error_message(self, error: str):
        """
        Send error message to channel.
        
        Args:
            error: Error text
        """
        if not self.channel:
            logger.warning("No Discord channel set")
            return
        
        try:
            embed = discord.Embed(
                title="⚠️ Error",
                description=error,
                color=discord.Color.orange()
            )
            await self.channel.send(embed=embed)
        
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")


# Global instance
_alerter: Optional[Alerter] = None


def init_alerter(discord_channel: Optional[discord.TextChannel] = None, config: dict = None):
    """
    Initialize global alerter.
    
    Args:
        discord_channel: Discord channel
        config: Config dict
    """
    global _alerter
    _alerter = Alerter(discord_channel, config)


def get_alerter() -> Alerter:
    """
    Get global alerter instance.
    
    Returns:
        Alerter instance
    """
    if _alerter is None:
        raise RuntimeError("Alerter not initialized. Call init_alerter() first.")
    return _alerter