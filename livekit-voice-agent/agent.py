import logging

from dotenv import load_dotenv
from livekit.agents import llm, stt, tts, inference   # ✅ Fixed: ttsx → tts, added inference
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RoomInputOptions,
    WorkerOptions,
    cli,
)
from livekit.plugins import noise_cancellation, silero

load_dotenv()


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                 "You are an upbeat, slightly sarcastic voice AI for tech support. "
    "Help the caller fix issues without rambling, and keep replies under 3 sentences."
            )
        )


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
        tts=tts.FallbackAdapter(   # ✅ Works now because tts is correctly imported
            [
                inference.TTS.from_model_string(
                    "cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
                ),
                inference.TTS.from_model_string("inworld/inworld-tts-1"),
            ]
        ),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )
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