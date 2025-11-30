"""
Discord bot setup and initialization.
Handles bot lifecycle, events, and command registration.
"""

import discord
from discord.ext import commands
import asyncio
from typing import Optional

from core.monitor import init_monitor, get_monitor
from core.alerter import init_alerter, get_alerter
from utils.logger import get_logger

import sys
import logging

logger = get_logger(__name__)


class MugBot(commands.Bot):
    """Custom Discord bot class for Torn Mug Bot."""
    
    def __init__(self, config: dict, alert_channel_id: int):
        """
        Initialize the bot.
        
        Args:
            config: Configuration dict
            alert_channel_id: Discord channel ID for alerts
        """
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(
            command_prefix="!",  # Not used (slash commands only)
            intents=intents,
            help_command=None
        )
        
        self.config = config
        self.alert_channel_id = alert_channel_id
        self.alert_channel: Optional[discord.TextChannel] = None
        self.monitor_task: Optional[asyncio.Task] = None
    
    async def setup_hook(self):
        """Called when bot is starting up."""
        logger.info("Setting up bot...")
        
        # Load commands cog
        await self.load_extension("bot.commands")
        
        # Sync slash commands
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
    
    async def on_ready(self):
        """Called when bot is ready and connected to Discord."""
        logger.info("=" * 60)
        logger.info(f"✅ Bot logged in as {self.user} (ID: {self.user.id})")
        logger.info("=" * 60)
        
        # Get alert channel
        try:
            self.alert_channel = self.get_channel(self.alert_channel_id)
            
            if not self.alert_channel:
                logger.error(f"Alert channel {self.alert_channel_id} not found!")
                return
            
            logger.info(f"Alert channel: #{self.alert_channel.name} ({self.alert_channel.id})")
            
            # Initialize alerter with channel
            init_alerter(self.alert_channel, self.config)
            
            # Initialize monitor
            init_monitor(self.config)
            
            # Start monitoring task
            self.monitor_task = asyncio.create_task(self.start_monitoring())
            
        except Exception as e:
            logger.error(f"Error in on_ready: {e}", exc_info=True)
    
    async def start_monitoring(self):
        """Start the monitoring loop."""
        try:
            # Wait a bit for everything to initialize
            await asyncio.sleep(2)
                        
            monitor = get_monitor()
            await monitor.start()
        
        except Exception as e:
            logger.error(f"Error in monitoring task: {e}", exc_info=True)
    
    async def on_command_error(self, ctx, error):
        """Handle command errors."""
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore unknown commands
        
        logger.error(f"Command error: {error}", exc_info=error)
    
    async def close(self):
        """Called when bot is shutting down."""
        logger.info("Shutting down bot...")
        
        # Stop monitoring
        try:
            monitor = get_monitor()
            monitor.stop()
            
            if self.monitor_task:
                self.monitor_task.cancel()
                try:
                    await self.monitor_task
                except asyncio.CancelledError:
                    pass
        except:
            pass
        
        # Send shutdown message
        try:
            alerter = get_alerter()
            await alerter.send_info_message("🛑 **Mug Bot Stopped** - Monitoring paused")
        except:
            pass
        
        await super().close()
        logger.info("Bot shutdown complete")


async def start_bot(token: str, config: dict, alert_channel_id: int):
    """
    Start the Discord bot.
    
    Args:
        token: Discord bot token
        config: Configuration dict
        alert_channel_id: Channel ID for alerts
    """
    bot = MugBot(config, alert_channel_id)
    
    try:
        await bot.start(token)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()