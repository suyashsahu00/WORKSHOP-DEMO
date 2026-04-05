import logging
import time
import httpx

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    AgentStateChangedEvent,
    JobContext,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
    llm,
    mcp,
    metrics,
    stt,
    tts,
    inference,
    ToolError,
)
from livekit.agents.metrics import ModelUsageCollector
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins import noise_cancellation, silero

load_dotenv()

logger = logging.getLogger("voice-agent")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are Sydney, a cheerful and friendly weather girl who loves talking about the weather. "
                "You provide accurate and engaging weather updates for any location asked. "
                "You use fun, expressive language to describe weather conditions like 'oh it's gloriously sunny!' or 'brrr, bundle up, it's freezing out there!'. "
                "You keep replies short, warm, and conversational. "
                "You can also look up the weather if asked. "
                "You can also answer questions about LiveKit by searching the documentation. "
                "When users ask about LiveKit features, APIs, or how to build something, use the docs search tools to find accurate information. "
                "If asked about topics outside weather and LiveKit, kindly redirect the conversation back to your specialties."
            ),
            mcp_servers=[
                mcp.MCPServerHTTP(url="https://docs.livekit.io/mcp"),
            ],
        )

    @function_tool
    async def lookup_weather(self, context: RunContext, location: str) -> dict:
        """Look up current weather for a location.

        Args:
            location: City name or location to get weather for.
        """
        await context.session.say("Let me check the weather for that!")
        logger.info("Looking up weather for %s", location)

        async with httpx.AsyncClient() as client:
            # First, geocode the location to get coordinates
            geo_response = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1},
            )
            geo_data = geo_response.json()

            if not geo_data.get("results"):
                raise ToolError(f"Location '{location}' not found.")

            result = geo_data["results"][0]
            lat = result["latitude"]
            lon = result["longitude"]
            city_name = result["name"]
            country = result.get("country", "")

            # Fetch weather using coordinates
            weather_response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,wind_speed_10m,weather_code",
                    "temperature_unit": "celsius",
                },
            )
            weather_data = weather_response.json()
            current = weather_data.get("current", {})

            return {
                "location": f"{city_name}, {country}",
                "temperature_celsius": current.get("temperature_2m"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "weather_code": current.get("weather_code"),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }


async def entrypoint(ctx: JobContext):
    session = AgentSession(
        stt=stt.FallbackAdapter(
            [
                inference.STT.from_model_string("assemblyai/universal-streaming:en"),
                inference.STT.from_model_string("deepgram/nova-3"),
            ]
        ),
        llm=llm.FallbackAdapter(
            [
                inference.LLM(model="openai/gpt-4.1-mini"),
                inference.LLM(model="google/gemini-2.5-flash"),
            ]
        ),
        tts=tts.FallbackAdapter(
            [
                inference.TTS.from_model_string(
                    "cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
                ),
                inference.TTS.from_model_string("inworld/inworld-tts-1"),
            ]
        ),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
        preemptive_generation=True,
        mcp_servers=[
            mcp.MCPServerHTTP(url="https://docs.livekit.io/mcp"),
        ],
    )

    # ── Metrics & Usage Tracking ─────────────────────────────────────────────
    usage_collector = ModelUsageCollector()

    @session.on("session_usage_updated")
    def _on_session_usage_updated(ev):
        logger.info("Session usage: %s", ev.usage)
        usage_collector.collect(ev.usage)

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: AgentStateChangedEvent):
        if ev.new_state == "speaking":
            logger.info("Agent started speaking (state -> speaking)")

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info("Usage summary: %s", summary)

    ctx.add_shutdown_callback(log_usage)
    # ─────────────────────────────────────────────────────────────────────────

    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )