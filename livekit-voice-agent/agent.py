import logging
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
    inference,
)
from livekit.plugins import noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv()
logger = logging.getLogger(__name__)


class ManagerAgent(Agent):
    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions=(
                "You are a customer service manager. "
                "You handle escalated issues that frontline agents could not resolve. "
                "Be empathetic, professional, and solution-focused. "
                "You have authority to offer refunds, credits, or other accommodations."
            ),
            chat_ctx=chat_ctx,
            tts=inference.TTS(
                model="cartesia/sonic-3",
                voice="6f84f4b8-58a2-430c-8c79-688dad597532",
            ),
        )

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions=(
                "Introduce yourself as the customer service manager and ask how you can help."
            )
        )


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a friendly customer service representative. "
                "Help customers with general inquiries. "
                "If they ask for a manager or you cannot resolve their issue, "
                "use the escalate_to_manager tool immediately."
            )
        )

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions="Greet the user warmly and offer your assistance."
        )

    @function_tool()
    async def escalate_to_manager(self, context: RunContext):
        """Transfer the customer to a manager when requested or when you cannot resolve the issue."""
        return ManagerAgent(chat_ctx=self.chat_ctx), "Transferring you to a manager now."


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    session = AgentSession(
        stt=inference.STT.from_model_string("assemblyai/universal-streaming:en"),
        llm=inference.LLM(model="openai/gpt-4.1-mini"),
        tts=inference.TTS.from_model_string(
            "cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
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


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )
