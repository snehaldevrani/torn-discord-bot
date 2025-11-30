"""
Discord bot command handlers.
Implements user commands for status, stats, and recent alerts.
"""

import discord
from discord.ext import commands
from discord import app_commands

from core.monitor import get_monitor
from database.models import AlertLogModel, MonitoredItemsModel
from database.db import get_database
from api.key_manager import get_key_manager
from utils.logger import get_logger
from utils.formatters import format_stats_message, format_recent_alerts, format_currency

logger = get_logger(__name__)


class BotCommands(commands.Cog):
    """Command handlers for the bot."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.alert_log = AlertLogModel()
        self.items_model = MonitoredItemsModel()
        self.db = get_database()
    
    @app_commands.command(name="status", description="Show bot status and statistics")
    async def status(self, interaction: discord.Interaction):
        """Show current bot status."""
        await interaction.response.defer()
        
        try:
            # Get monitor stats
            monitor = get_monitor()
            monitor_stats = monitor.get_stats()
            
            # Get database stats
            db_stats = await self.db.get_database_stats()
            
            # Get API key stats
            try:
                key_manager = get_key_manager()
                key_stats = key_manager.get_stats()
            except:
                key_stats = {'total_keys': 0, 'available': 0}
            
            # Get 24h alerts
            alerts_24h = await self.alert_log.get_alerts_24h()
            
            # Format status message
            embed = discord.Embed(
                title="🤖 Mug Bot Status",
                color=discord.Color.green() if monitor_stats.get('is_running') else discord.Color.red(),
                description="Current bot statistics and performance"
            )
            
            # Status field
            status_emoji = "🟢" if monitor_stats.get('is_running') else "🔴"
            embed.add_field(
                name=f"{status_emoji} Status",
                value="Running" if monitor_stats.get('is_running') else "Stopped",
                inline=True
            )
            
            # Uptime
            if monitor_stats.get('uptime'):
                embed.add_field(
                    name="⏱️ Uptime",
                    value=monitor_stats['uptime'],
                    inline=True
                )
            
            # Cycles
            embed.add_field(
                name="🔄 Cycles",
                value=f"{monitor_stats.get('cycle_count', 0):,}",
                inline=True
            )
            
            # Active targets
            embed.add_field(
                name="🎯 Active Targets",
                value=f"{db_stats.get('tracked_targets', 0)}",
                inline=True
            )
            
            # Alerts
            embed.add_field(
                name="🚨 Alerts (24h)",
                value=f"{alerts_24h:,}",
                inline=True
            )
            
            # Total alerts
            embed.add_field(
                name="📊 Total Alerts",
                value=f"{monitor_stats.get('total_alerts_sent', 0):,}",
                inline=True
            )
            
            # API Keys
            embed.add_field(
                name="🔑 API Keys",
                value=f"{key_stats.get('available', 0)}/{key_stats.get('total_keys', 0)} available",
                inline=True
            )
            
            # Database
            embed.add_field(
                name="💾 Database",
                value=db_stats.get('database_size', 'Unknown'),
                inline=True
            )
            
            # Check interval
            embed.add_field(
                name="⏰ Check Interval",
                value=f"{monitor_stats.get('check_interval', 0)}s",
                inline=True
            )
            
            embed.set_footer(text="Use /recent to see recent alerts")
            
            await interaction.followup.send(embed=embed)
            logger.info(f"Status command used by {interaction.user}")
        
        except Exception as e:
            logger.error(f"Error in status command: {e}", exc_info=True)
            await interaction.followup.send("❌ Error retrieving status", ephemeral=True)
    
    @app_commands.command(name="recent", description="Show recent mug alerts")
    @app_commands.describe(limit="Number of alerts to show (default: 10)")
    async def recent(self, interaction: discord.Interaction, limit: int = 10):
        """Show recent alerts."""
        await interaction.response.defer()
        
        try:
            if limit < 1 or limit > 50:
                await interaction.followup.send("❌ Limit must be between 1 and 50", ephemeral=True)
                return
            
            # Get recent alerts
            alerts = await self.alert_log.get_recent_alerts(limit)
            
            if not alerts:
                embed = discord.Embed(
                    description="No recent alerts found.",
                    color=discord.Color.blue()
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Create embed
            embed = discord.Embed(
                title=f"📋 Recent Alerts (Last {len(alerts)})",
                color=discord.Color.blue()
            )
            
            for i, alert in enumerate(alerts, 1):
                player_name = alert.get('player_name', 'Unknown')
                player_id = alert.get('player_id', 0)
                value = alert.get('accumulated_value', 0)
                minutes = alert.get('last_action_minutes', 0)
                status = alert.get('status_state', 'Unknown')
                timestamp = alert.get('alerted_at', '')
                
                embed.add_field(
                    name=f"{i}. {player_name} ({player_id})",
                    value=(
                        f"💰 {format_currency(value)} | "
                        f"⏱️ {minutes}m ago | "
                        f"📍 {status}\n"
                        f"🕐 {timestamp}"
                    ),
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            logger.info(f"Recent command used by {interaction.user} (limit: {limit})")
        
        except Exception as e:
            logger.error(f"Error in recent command: {e}", exc_info=True)
            await interaction.followup.send("❌ Error retrieving recent alerts", ephemeral=True)
    
    @app_commands.command(name="stats", description="Show detailed statistics")
    async def stats(self, interaction: discord.Interaction):
        """Show detailed statistics."""
        await interaction.response.defer()
        
        try:
            # Get various stats
            monitor = get_monitor()
            monitor_stats = monitor.get_stats()
            
            db_stats = await self.db.get_database_stats()
            
            tracker = monitor.tracker
            total_value = await tracker.get_total_tracked_value()
            
            alerts_24h = await self.alert_log.get_alerts_24h()
            
            # Get monitored items
            items = await self.items_model.get_enabled_items()
            items_str = ", ".join([item['item_name'] for item in items]) if items else "None"
            
            # Create embed
            embed = discord.Embed(
                title="📊 Detailed Statistics",
                color=discord.Color.purple()
            )
            
            # Monitor stats
            embed.add_field(
                name="⏱️ Monitoring",
                value=(
                    f"**Uptime:** {monitor_stats.get('uptime', 'N/A')}\n"
                    f"**Cycles:** {monitor_stats.get('cycle_count', 0):,}\n"
                    f"**Interval:** {monitor_stats.get('check_interval', 0)}s"
                ),
                inline=True
            )
            
            # Detection stats
            embed.add_field(
                name="🔍 Detection",
                value=(
                    f"**Sales Found:** {monitor_stats.get('total_sales_detected', 0):,}\n"
                    f"**Active Targets:** {db_stats.get('tracked_targets', 0)}\n"
                    f"**Total Value:** {format_currency(total_value)}"
                ),
                inline=True
            )
            
            # Alert stats
            embed.add_field(
                name="🚨 Alerts",
                value=(
                    f"**Total Sent:** {monitor_stats.get('total_alerts_sent', 0):,}\n"
                    f"**Last 24h:** {alerts_24h:,}\n"
                    f"**In Log:** {db_stats.get('total_alerts', 0):,}"
                ),
                inline=True
            )
            
            # Items monitored
            embed.add_field(
                name="📦 Monitored Items",
                value=items_str,
                inline=False
            )
            
            # Thresholds
            embed.add_field(
                name="⚙️ Configuration",
                value=(
                    f"**Min Accumulated:** {format_currency(monitor_stats.get('min_accumulated', 0))}\n"
                    f"**Min Inactivity:** {monitor_stats.get('min_inactivity_minutes', 0)} minutes"
                ),
                inline=False
            )
            
            # Database
            embed.add_field(
                name="💾 Database",
                value=(
                    f"**Size:** {db_stats.get('database_size', 'Unknown')}\n"
                    f"**Bazaar Records:** {db_stats.get('bazaar_records', 0):,}\n"
                    f"**Alert Records:** {db_stats.get('total_alerts', 0):,}"
                ),
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            logger.info(f"Stats command used by {interaction.user}")
        
        except Exception as e:
            logger.error(f"Error in stats command: {e}", exc_info=True)
            await interaction.followup.send("❌ Error retrieving statistics", ephemeral=True)
    
    @app_commands.command(name="help", description="Show help information")
    async def help_command(self, interaction: discord.Interaction):
        """Show help information."""
        embed = discord.Embed(
            title="📖 Mug Bot Help",
            description="Automated bazaar monitoring for mug targets",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="/status",
            value="Show current bot status and key statistics",
            inline=False
        )
        
        embed.add_field(
            name="/recent [limit]",
            value="Show recent mug alerts (default: 10, max: 50)",
            inline=False
        )
        
        embed.add_field(
            name="/stats",
            value="Show detailed statistics and configuration",
            inline=False
        )
        
        embed.add_field(
            name="/help",
            value="Show this help message",
            inline=False
        )
        
        embed.add_field(
            name="ℹ️ How It Works",
            value=(
                "The bot monitors bazaar listings every 15 seconds. "
                "When a player sells items worth $10M+, the bot checks if they're "
                "inactive (2+ minutes). If so, an alert is sent with their profile and attack link."
            ),
            inline=False
        )
        
        embed.set_footer(text="Developed for Torn City")
        
        await interaction.response.send_message(embed=embed)
        logger.info(f"Help command used by {interaction.user}")


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    await bot.add_cog(BotCommands(bot))