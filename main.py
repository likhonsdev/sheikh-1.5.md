"""
Sheikh 1.5 - Production Grade AI Proxy System
============================================
Author: Likhon Sheikh | t.me/likhonsheikh
Version: 3.0 Enhanced
License: Proprietary © 2025 Likhon Sheikh

Features:
- ✅ Streaming responses (SSE)
- ✅ Rate limiting & authentication
- ✅ Advanced error handling
- ✅ Request validation & sanitization
- ✅ Analytics & logging
- ✅ Environment configuration
- ✅ CORS support
- ✅ Health checks
"""

import os
import json
import asyncio
import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator
import httpx
import redis.asyncio as redis
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# -------------------------------
# Logging Configuration
# -------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("sheikh-1.5")

# -------------------------------
# Environment Configuration
# -------------------------------
class Config:
    MISTRAL_URL = os.getenv("MISTRAL_URL", "https://mistral-ai.chat/wp-admin/admin-ajax.php")
    MISTRAL_NONCE = os.getenv("MISTRAL_NONCE", "83103efe99")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    API_SECRET_KEY = os.getenv("API_SECRET_KEY", "sheikh-1.5-secret-key")
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    MAX_REQUESTS_PER_MINUTE = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "30"))
    MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))
    ENABLE_ANALYTICS = os.getenv("ENABLE_ANALYTICS", "true").lower() == "true"

config = Config()

# -------------------------------
# Redis & Rate Limiter Setup
# -------------------------------
try:
    redis_client = redis.from_url(config.REDIS_URL, decode_responses=True)
    limiter = Limiter(key_func=get_remote_address, storage_uri=config.REDIS_URL)
except Exception as e:
    logger.warning(f"Redis not available, using in-memory rate limiting: {e}")
    limiter = Limiter(key_func=get_remote_address)
    redis_client = None

# -------------------------------
# Lifespan Events
# -------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Sheikh 1.5 API starting up...")
    if redis_client:
        await redis_client.ping()
        logger.info("✅ Redis connection established")
    yield
    # Shutdown
    logger.info("🛑 Sheikh 1.5 API shutting down...")
    if redis_client:
        await redis_client.close()

# -------------------------------
# FastAPI App Configuration
# -------------------------------
app = FastAPI(
    title="Sheikh 1.5 - Enhanced AI Proxy",
    description="Production-grade FastAPI wrapper for AI with streaming, auth, and analytics",
    version="3.0",
    contact={
        "name": "Likhon Sheikh",
        "url": "https://t.me/likhonsheikh",
        "email": "contact@likhonsheikh.com"
    },
    lifespan=lifespan
)

# Add rate limiting middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if config.ENVIRONMENT == "development" else [
        "https://your-domain.com",
        "https://sheikh-1-5.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# Security & Authentication
# -------------------------------
security = HTTPBearer(auto_error=False)

async def verify_api_key(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """Verify API key for protected endpoints"""
    if config.ENVIRONMENT == "development":
        return True

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required"
        )

    if credentials.credentials != config.API_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    return True

# -------------------------------
# Request Models
# -------------------------------
class ChatRequest(BaseModel):
    text: str = Field(..., description="User input text", min_length=1)
    persona: str = Field("Sheikh 1.5", description="AI persona override", max_length=100)
    style: str = Field("friendly, professional", description="Response style", max_length=200)
    tags: str = Field("AI, help, guidance", description="Response guidance tags", max_length=300)
    stream: bool = Field(False, description="Enable streaming response")
    temperature: float = Field(0.7, description="Response creativity (0.0-1.0)", ge=0.0, le=1.0)

    @validator('text')
    def validate_text_length(cls, v):
        if len(v) > config.MAX_MESSAGE_LENGTH:
            raise ValueError(f'Text too long (max {config.MAX_MESSAGE_LENGTH} characters)')
        return v.strip()

    @validator('text', 'persona', 'style', 'tags')
    def sanitize_input(cls, v):
        """Basic sanitization to prevent injection attacks"""
        if isinstance(v, str):
            # Remove potentially dangerous characters
            dangerous_chars = ['<script', '</script', 'javascript:', 'eval(', 'exec(']
            for char in dangerous_chars:
                if char.lower() in v.lower():
                    raise ValueError('Invalid characters detected')
        return v

class AnalyticsEvent(BaseModel):
    event_type: str
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = {}

# -------------------------------
# Analytics & Logging
# -------------------------------
class Analytics:
    @staticmethod
    async def log_request(request: Request, response_time: float, success: bool, message_length: int):
        """Log request analytics"""
        if not config.ENABLE_ANALYTICS or not redis_client:
            return

        try:
            timestamp = datetime.now().isoformat()
            analytics_data = {
                "timestamp": timestamp,
                "ip": get_remote_address(request),
                "user_agent": request.headers.get("user-agent", "unknown"),
                "response_time": response_time,
                "success": success,
                "message_length": message_length
            }

            # Store in Redis with TTL of 30 days
            key = f"analytics:{timestamp}"
            await redis_client.setex(key, 2592000, json.dumps(analytics_data))

            # Update counters
            today = datetime.now().strftime("%Y-%m-%d")
            await redis_client.incr(f"requests:daily:{today}")
            await redis_client.expire(f"requests:daily:{today}", 86400 * 7)  # Keep for 7 days

        except Exception as e:
            logger.error(f"Analytics logging failed: {e}")

# -------------------------------
# Enhanced Prompt Builder
# -------------------------------
def build_enhanced_prompt(
    user_text: str,
    persona: str = "Sheikh 1.5",
    style: str = "friendly, professional",
    tags: str = "AI, help, guidance",
    temperature: float = 0.7
) -> str:
    """Build enhanced prompt with context awareness"""

    # Context-aware instructions based on input
    context_hints = []
    if any(word in user_text.lower() for word in ['code', 'programming', 'debug']):
        context_hints.append("technical, code-focused")
    if any(word in user_text.lower() for word in ['urgent', 'help', 'problem']):
        context_hints.append("supportive, solution-oriented")

    context = ", ".join(context_hints) if context_hints else "general assistance"

    return f"""[SYSTEM_INSTRUCTION]
persona: {persona}
style: {style}
tags: {tags}
context: {context}
temperature: {temperature}
timestamp: {datetime.now().isoformat()}
[/SYSTEM_INSTRUCTION]

[USER_REQUEST]
{user_text}
[/USER_REQUEST]

[RESPONSE_GUIDELINES]
- Maintain {persona} personality consistently
- Use {style} communication approach
- Focus on {tags} themes
- Provide helpful, accurate information
- Be culturally aware and respectful
[/RESPONSE_GUIDELINES]"""

# -------------------------------
# Enhanced Mistral API Client
# -------------------------------
class MistralClient:
    def __init__(self):
        self.session = None

    async def get_session(self):
        if not self.session:
            self.session = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        return self.session

    async def query_mistral(self, message: str, stream: bool = False):
        """Enhanced Mistral API query with retry logic"""
        payload = {
            "action": "ai_chat_response",
            "message": message,
            "nonce": config.MISTRAL_NONCE,
            "stream": "1" if stream else "0"
        }

        headers = {
            "User-Agent": "Sheikh-1.5-Enhanced/3.0",
            "Accept": "application/json" if not stream else "text/stream",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://mistral-ai.chat/",
            "Origin": "https://mistral-ai.chat"
        }

        session = await self.get_session()

        # Retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await session.post(
                    config.MISTRAL_URL,
                    data=payload,
                    headers=headers
                )
                response.raise_for_status()

                if stream:
                    return response
                else:
                    api_response = response.json()
                    return api_response.get("data", {}).get("message", "AI সাময়িকভাবে অনুপস্থিত!")

            except httpx.TimeoutException:
                if attempt == max_retries - 1:
                    return "⏱️ API timeout - আবার চেষ্টা করুন"
                await asyncio.sleep(2 ** attempt)
            except httpx.HTTPError as e:
                if attempt == max_retries - 1:
                    return f"🚫 API Error: {str(e)}"
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Mistral API error (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return f"❌ Unexpected error: {str(e)}"
                await asyncio.sleep(2 ** attempt)

mistral_client = MistralClient()

# -------------------------------
# Health Check Endpoint
# -------------------------------
@app.get("/health")
async def health_check():
    """System health check"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "3.0",
        "services": {}
    }

    # Check Redis
    if redis_client:
        try:
            await redis_client.ping()
            health_status["services"]["redis"] = "connected"
        except:
            health_status["services"]["redis"] = "disconnected"
            health_status["status"] = "degraded"

    # Check Mistral API
    try:
        test_response = await mistral_client.query_mistral("health check")
        health_status["services"]["mistral"] = "available"
    except:
        health_status["services"]["mistral"] = "unavailable"
        health_status["status"] = "degraded"

    return health_status

# -------------------------------
# Analytics Endpoint
# -------------------------------
@app.get("/analytics")
@limiter.limit("10/minute")
async def get_analytics(request: Request, auth: bool = Depends(verify_api_key)):
    """Get analytics data (protected endpoint)"""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Analytics not available")

    try:
        today = datetime.now().strftime("%Y-%m-%d")
        daily_requests = await redis_client.get(f"requests:daily:{today}") or 0

        # Get recent analytics (last 10 requests)
        keys = await redis_client.keys("analytics:*")
        recent_keys = sorted(keys, reverse=True)[:10]

        recent_analytics = []
        for key in recent_keys:
            data = await redis_client.get(key)
            if data:
                recent_analytics.append(json.loads(data))

        return {
            "daily_requests": int(daily_requests),
            "recent_requests": recent_analytics,
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Analytics retrieval error: {e}")
        raise HTTPException(status_code=500, detail="Analytics retrieval failed")

# -------------------------------
# GET Endpoint (Quick Queries)
# -------------------------------
@app.get("/chat")
@limiter.limit(f"{config.MAX_REQUESTS_PER_MINUTE}/minute")
async def chat_get(
    request: Request,
    text: str = Query(..., description="Your message"),
    persona: str = Query("Sheikh 1.5", description="AI persona"),
    style: str = Query("friendly, professional", description="Response style"),
    tags: str = Query("AI, help, guidance", description="Response tags"),
    stream: bool = Query(False, description="Enable streaming"),
    temperature: float = Query(0.7, description="Response creativity", ge=0.0, le=1.0)
):
    start_time = time.time()

    try:
        # Input validation
        if len(text) > config.MAX_MESSAGE_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Text too long (max {config.MAX_MESSAGE_LENGTH} characters)"
            )

        prompt = build_enhanced_prompt(text, persona, style, tags, temperature)

        if stream:
            async def generate_stream():
                try:
                    response = await mistral_client.query_mistral(prompt, stream=True)
                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                    yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*"
                }
            )
        else:
            message = await mistral_client.query_mistral(prompt)
            response_time = time.time() - start_time

            # Log analytics
            await Analytics.log_request(request, response_time, True, len(text))

            return JSONResponse(content={
                "status": "✅ Success",
                "message": message,
                "metadata": {
                    "persona": persona,
                    "style": style,
                    "response_time": f"{response_time:.2f}s",
                    "version": "3.0"
                },
                "credits": {
                    "author": "Likhon Sheikh",
                    "telegram": "t.me/likhonsheikh"
                }
            })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat GET error: {e}")
        await Analytics.log_request(request, time.time() - start_time, False, len(text))
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# -------------------------------
# POST Endpoint (Advanced Queries)
# -------------------------------
@app.post("/chat")
@limiter.limit(f"{config.MAX_REQUESTS_PER_MINUTE}/minute")
async def chat_post(
    request: Request,
    chat_request: ChatRequest = Body(..., examples={
        "basic": {
            "summary": "Basic Sheikh 1.5 query",
            "description": "Simple message with default persona",
            "value": {
                "text": "আজকে কেমন আছো?",
                "persona": "Sheikh 1.5"
            }
        },
        "technical": {
            "summary": "Technical query with streaming",
            "description": "Technical question with streaming enabled",
            "value": {
                "text": "Explain Python asyncio with examples",
                "persona": "Sheikh 1.5 - Technical Expert",
                "style": "technical, detailed",
                "tags": "programming, python, async",
                "stream": True,
                "temperature": 0.3
            }
        },
        "creative": {
            "summary": "Creative writing request",
            "description": "Creative content with higher temperature",
            "value": {
                "text": "Write a short story about AI and humans",
                "persona": "Sheikh 1.5 - Creative Writer",
                "style": "creative, engaging",
                "tags": "storytelling, AI, future",
                "temperature": 0.9
            }
        }
    })
):
    start_time = time.time()

    try:
        prompt = build_enhanced_prompt(
            chat_request.text,
            chat_request.persona,
            chat_request.style,
            chat_request.tags,
            chat_request.temperature
        )

        if chat_request.stream:
            async def generate_advanced_stream():
                try:
                    # Send initial metadata
                    metadata = {
                        "type": "metadata",
                        "persona": chat_request.persona,
                        "style": chat_request.style,
                        "temperature": chat_request.temperature
                    }
                    yield f"data: {json.dumps(metadata)}\n\n"

                    # Stream response
                    response = await mistral_client.query_mistral(prompt, stream=True)
                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            chunk_data = {
                                "type": "content",
                                "chunk": chunk,
                                "done": False
                            }
                            yield f"data: {json.dumps(chunk_data)}\n\n"

                    # Send completion signal
                    completion_data = {
                        "type": "completion",
                        "done": True,
                        "response_time": f"{time.time() - start_time:.2f}s"
                    }
                    yield f"data: {json.dumps(completion_data)}\n\n"

                except Exception as e:
                    error_data = {
                        "type": "error",
                        "error": str(e),
                        "done": True
                    }
                    yield f"data: {json.dumps(error_data)}\n\n"

            return StreamingResponse(
                generate_advanced_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "X-Content-Type-Options": "nosniff"
                }
            )
        else:
            message = await mistral_client.query_mistral(prompt)
            response_time = time.time() - start_time

            # Log analytics
            await Analytics.log_request(request, response_time, True, len(chat_request.text))

            return JSONResponse(content={
                "status": "✅ Advanced Processing Complete",
                "message": message,
                "request_metadata": {
                    "persona": chat_request.persona,
                    "style": chat_request.style,
                    "tags": chat_request.tags,
                    "temperature": chat_request.temperature,
                    "text_length": len(chat_request.text)
                },
                "response_metadata": {
                    "response_time": f"{response_time:.2f}s",
                    "processing_mode": "advanced",
                    "version": "3.0"
                },
                "credits": {
                    "author": "Likhon Sheikh",
                    "telegram": "t.me/likhonsheikh",
                    "version": "3.0 Enhanced"
                }
            })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat POST error: {e}")
        await Analytics.log_request(request, time.time() - start_time, False, len(chat_request.text))
        raise HTTPException(status_code=500, detail=f"Advanced processing failed: {str(e)}")

# -------------------------------
# Custom Error Handlers
# -------------------------------
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "error": "🚫 Endpoint not found",
            "message": "দোস্ত, ভুল রাস্তায় চলে এসেছো!",
            "available_endpoints": ["/chat", "/health", "/analytics", "/docs"],
            "credits": {"author": "Likhon Sheikh", "telegram": "t.me/likhonsheikh"}
        }
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "🔧 Internal server error",
            "message": "সিস্টেমে সমস্যা! আমরা ঠিক করে দিচ্ছি।",
            "credits": {"author": "Likhon Sheikh", "telegram": "t.me/likhonsheikh"}
        }
    )

# -------------------------------
# Startup Message
# -------------------------------
@app.on_event("startup")
async def startup_message():
    logger.info("🎯 Sheikh 1.5 Enhanced API - Ready for Production!")
    logger.info("📱 Contact: t.me/likhonsheikh")
    logger.info("🌟 Features: Streaming, Auth, Analytics, Rate Limiting")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True if config.ENVIRONMENT == "development" else False,
        log_level="info"
    )
