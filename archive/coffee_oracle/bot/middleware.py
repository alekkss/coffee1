"""Bot middleware for handling media groups."""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = logging.getLogger(__name__)

# Storage for collecting media group messages
# Key: media_group_id, Value: {"messages": [...], "task": asyncio.Task}
_media_groups: Dict[str, Dict[str, Any]] = {}

# Time to wait for more photos in a media group (seconds)
MEDIA_GROUP_COLLECT_TIMEOUT = 1.0


class MediaGroupMiddleware(BaseMiddleware):
    """Middleware to collect photos from media groups."""
    
    def __init__(self):
        self.lock = asyncio.Lock()
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Only process Message events with photos
        if not isinstance(event, Message) or not event.photo:
            return await handler(event, data)
        
        message: Message = event
        
        # If no media_group_id, process as single photo
        if not message.media_group_id:
            data["media_group_photos"] = [message]
            data["is_media_group"] = False
            return await handler(event, data)
        
        media_group_id = message.media_group_id
        
        async with self.lock:
            if media_group_id not in _media_groups:
                # First photo in group - create entry and schedule processing
                _media_groups[media_group_id] = {
                    "messages": [message],
                    "processed": False,
                    "caption": message.caption,  # Caption is usually on first photo
                }
                
                # Schedule delayed processing
                asyncio.create_task(
                    self._process_media_group_delayed(
                        media_group_id, handler, data.copy()
                    )
                )
                
                # Don't call handler yet - wait for more photos
                return None
            else:
                # Additional photo in group - add to collection
                group_data = _media_groups[media_group_id]
                
                if group_data["processed"]:
                    # Group already processed, ignore late arrivals
                    return None
                
                group_data["messages"].append(message)
                
                # Capture caption if this message has one
                if message.caption and not group_data["caption"]:
                    group_data["caption"] = message.caption
                
                # Don't call handler - will be called by delayed task
                return None
    
    async def _process_media_group_delayed(
        self,
        media_group_id: str,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        data: Dict[str, Any]
    ) -> None:
        """Wait for all photos and then process the group."""
        # Wait for more photos to arrive
        await asyncio.sleep(MEDIA_GROUP_COLLECT_TIMEOUT)
        
        async with self.lock:
            if media_group_id not in _media_groups:
                return
            
            group_data = _media_groups[media_group_id]
            
            if group_data["processed"]:
                return
            
            group_data["processed"] = True
            messages = group_data["messages"]
            caption = group_data["caption"]
        
        # Sort messages by message_id to maintain order
        messages.sort(key=lambda m: m.message_id)
        
        logger.info(
            "Processing media group %s with %d photos",
            media_group_id, len(messages)
        )
        
        # Use first message as the main event
        first_message = messages[0]
        
        # Override caption if it was on another message
        if caption:
            # Create a copy-like behavior by setting caption
            first_message._caption = caption
        
        # Add media group data to handler context
        data["media_group_photos"] = messages
        data["is_media_group"] = True
        data["media_group_caption"] = caption
        
        try:
            await handler(first_message, data)
        except Exception as e:
            logger.error("Error processing media group %s: %s", media_group_id, e)
        finally:
            # Cleanup
            async with self.lock:
                _media_groups.pop(media_group_id, None)
